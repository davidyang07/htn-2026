"""Postgres-backed coverage for the read-only history API: pagination
cursors, filtering, 404s, replay-snapshot's last_seq matching
MAX(seq) WHERE sim_tick=0, and event-log pagination across a full run with
no gaps or duplicates."""

import asyncio
import json
import uuid

from fastapi.testclient import TestClient

from app.db import create_pool
from app.main import app
from app.orchestrator.runner import ExperimentRunner
from app.persistence.registry import writer_registry
from app.persistence.writer import PostgresWriter
from app.schemas.experiment import ExperimentConfig

from .conftest import TEST_SETTINGS, requires_postgres

pytestmark = requires_postgres


def _make_runner(**overrides) -> ExperimentRunner:
    defaults = {"seed": 42, "node_count": 25, "max_ticks": 5}
    defaults.update(overrides)
    runner = ExperimentRunner(ExperimentConfig(**defaults))
    runner.tick_interval = 0
    return runner


async def _persist_completed_run(pool, **config_overrides) -> ExperimentRunner:
    runner = _make_runner(**config_overrides)
    # Mirrors the exact production call site in routes_experiments.py --
    # writer_registry.add() happens at the call site, not inside
    # PostgresWriter itself.
    writer = PostgresWriter(pool, runner.experiment_id, runner.bus, runner)
    await writer.start()
    writer_registry.add(runner.experiment_id, writer)
    await runner.publish_initial()
    await runner._run_loop()

    deadline = asyncio.get_event_loop().time() + 5.0
    while not writer._task.done():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("writer did not finalize within the timeout")
        await asyncio.sleep(0.01)
    return runner


async def _cleanup(*experiment_ids: object) -> None:
    # Self-contained: creates and closes its own pool within this single
    # asyncio.run() call. asyncpg pools/connections are bound to the event
    # loop that created them, so a pool created in an earlier, separate
    # asyncio.run() call (whose loop is already closed by the time this
    # runs) cannot be reused here.
    pool = await create_pool(TEST_SETTINGS)
    try:
        for experiment_id in experiment_ids:
            await pool.execute("DELETE FROM experiments WHERE experiment_id = $1", experiment_id)
    finally:
        await pool.close()


def test_detail_and_events_and_replay_snapshot_for_a_persisted_run():
    async def setup() -> ExperimentRunner:
        pool = await create_pool(TEST_SETTINGS)
        try:
            return await _persist_completed_run(pool)
        finally:
            await pool.close()

    runner = asyncio.run(setup())
    try:
        with TestClient(app) as client:
            exp_id = str(runner.experiment_id)

            detail = client.get(f"/api/experiments/{exp_id}/detail")
            assert detail.status_code == 200
            body = detail.json()
            assert body["experiment_id"] == exp_id
            assert body["final_status"] == "finished"
            assert body["is_complete"] is True

            snapshot = client.get(f"/api/experiments/{exp_id}/replay-snapshot")
            assert snapshot.status_code == 200
            snap_body = snapshot.json()
            assert snap_body["type"] == "snapshot"
            assert len(snap_body["nodes"]) == 25
            assert len(snap_body["edges"]) > 0

            # replay-snapshot's last_seq must equal MAX(seq) WHERE sim_tick=0
            # -- the exact boundary that prevents the seed compromise from
            # being double-delivered by the next /events page.
            events_page = client.get(
                f"/api/experiments/{exp_id}/events",
                params={"since_seq": snap_body["last_seq"]},
            )
            assert events_page.status_code == 200
            first_returned = events_page.json()["events"][0]
            assert first_returned["sim_tick"] >= 1 or first_returned["seq"] > snap_body["last_seq"]
            assert all(e["sim_tick"] != 0 for e in events_page.json()["events"])

            # Paginate the full log to completion via next_seq: no gaps, no dupes.
            all_seqs: list[int] = []
            since_seq = -1
            while True:
                page = client.get(
                    f"/api/experiments/{exp_id}/events",
                    params={"since_seq": since_seq, "limit": 50},
                )
                assert page.status_code == 200
                body = page.json()
                all_seqs.extend(e["seq"] for e in body["events"])
                if body["next_seq"] is None:
                    break
                since_seq = body["next_seq"]
            assert all_seqs == list(range(runner._emitter.last_seq + 1))
            assert len(all_seqs) == len(set(all_seqs))
    finally:
        asyncio.run(_cleanup(runner.experiment_id))


def test_incidents_endpoint_only_returns_incident_event_types():
    async def setup() -> ExperimentRunner:
        pool = await create_pool(TEST_SETTINGS)
        try:
            return await _persist_completed_run(pool, p_same=1.0, p_cross=1.0)
        finally:
            await pool.close()

    runner = asyncio.run(setup())
    try:
        with TestClient(app) as client:
            resp = client.get(f"/api/experiments/{runner.experiment_id}/incidents")
            assert resp.status_code == 200
            events = resp.json()["events"]
            assert events, "expected propagation to produce incident events"
            incident_types = {
                "COMPROMISE_ATTEMPTED",
                "COMPROMISE_SUCCEEDED",
                "COMPROMISE_FAILED",
                "ANOMALY_DETECTED",
                "AGENT_QUARANTINED",
            }
            assert all(e["event_type"] in incident_types for e in events)
    finally:
        asyncio.run(_cleanup(runner.experiment_id))


def test_list_filters_and_paginates_by_status_and_defense_enabled():
    async def setup() -> tuple[ExperimentRunner, ExperimentRunner]:
        pool = await create_pool(TEST_SETTINGS)
        try:
            on = await _persist_completed_run(pool, seed=1, defense_enabled=True)
            off = await _persist_completed_run(pool, seed=2, defense_enabled=False)
            return on, off
        finally:
            await pool.close()

    on_runner, off_runner = asyncio.run(setup())
    try:
        with TestClient(app) as client:
            resp = client.get("/api/experiments", params={"defense_enabled": "true", "limit": 100})
            assert resp.status_code == 200
            ids = {item["experiment_id"] for item in resp.json()["items"]}
            assert str(on_runner.experiment_id) in ids
            assert str(off_runner.experiment_id) not in ids

            resp = client.get("/api/experiments", params={"status": "finished", "limit": 1})
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["items"]) == 1
            if body["next_cursor"]:
                params = {"status": "finished", "limit": 1, "cursor": body["next_cursor"]}
                resp2 = client.get("/api/experiments", params=params)
                assert resp2.status_code == 200
                next_id = resp2.json()["items"][0]["experiment_id"]
                assert next_id != body["items"][0]["experiment_id"]
    finally:
        asyncio.run(_cleanup(on_runner.experiment_id, off_runner.experiment_id))


def test_history_endpoints_404_for_unknown_experiment():
    with TestClient(app) as client:
        fake_id = uuid.uuid4()
        assert client.get(f"/api/experiments/{fake_id}/detail").status_code == 404
        assert client.get(f"/api/experiments/{fake_id}/events").status_code == 404
        assert client.get(f"/api/experiments/{fake_id}/incidents").status_code == 404
        assert client.get(f"/api/experiments/{fake_id}/replay-snapshot").status_code == 404


def test_history_endpoints_503_when_pool_unavailable():
    with TestClient(app) as client:
        client.app.state.pg_pool = None
        fake_id = uuid.uuid4()
        assert client.get("/api/experiments").status_code == 503
        assert client.get(f"/api/experiments/{fake_id}/detail").status_code == 503


def test_replay_graph_metrics_remediation_match_a_live_equivalent_run():
    # Same config run twice: once through the live path (registry + /graph,
    # /metrics, /remediation), once persisted and read back through the new
    # /replay/* endpoints -- since both reconstruct the exact same
    # deterministic (seed, config) run, their outputs must be identical.
    config_kwargs = {
        "seed": 9,
        "node_count": 30,
        "p_same": 0.3,
        "max_ticks": 10,
        "sentinel_count": 1,
    }

    async def setup() -> ExperimentRunner:
        pool = await create_pool(TEST_SETTINGS)
        try:
            return await _persist_completed_run(pool, **config_kwargs)
        finally:
            await pool.close()

    runner = asyncio.run(setup())
    try:
        with TestClient(app) as client:
            live = ExperimentRunner(ExperimentConfig(**config_kwargs))
            live.tick_interval = 0

            async def run_live() -> None:
                await live.publish_initial()
                await live._run_loop()

            asyncio.run(run_live())
            from app.orchestrator.registry import registry

            registry.add(live)
            try:
                live_graph = client.get(f"/api/experiments/{live.experiment_id}/graph").json()
                live_metrics = client.get(f"/api/experiments/{live.experiment_id}/metrics").json()
                live_remediation = client.get(
                    f"/api/experiments/{live.experiment_id}/remediation"
                ).json()
            finally:
                registry.remove(live.experiment_id)

            exp_id = runner.experiment_id
            replay_graph = client.get(f"/api/experiments/{exp_id}/replay/graph")
            assert replay_graph.status_code == 200
            replay_metrics = client.get(f"/api/experiments/{exp_id}/replay/metrics")
            assert replay_metrics.status_code == 200
            replay_remediation = client.get(f"/api/experiments/{exp_id}/replay/remediation")
            assert replay_remediation.status_code == 200

            assert replay_graph.json() == live_graph
            assert replay_metrics.json() == live_metrics
            assert replay_remediation.json() == live_remediation
    finally:
        asyncio.run(_cleanup(runner.experiment_id))


def test_replay_analysis_endpoints_return_200_for_a_persisted_run():
    async def setup() -> ExperimentRunner:
        pool = await create_pool(TEST_SETTINGS)
        try:
            return await _persist_completed_run(pool, seed=4, node_count=25, p_same=0.4)
        finally:
            await pool.close()

    runner = asyncio.run(setup())
    try:
        with TestClient(app) as client:
            exp_id = runner.experiment_id
            graph = client.get(f"/api/experiments/{exp_id}/replay/graph").json()
            edge = graph["edges"][0]

            resp = client.get(
                f"/api/experiments/{exp_id}/replay/analysis/attack-paths",
                params={"source": edge["source"], "target": edge["target"]},
            )
            assert resp.status_code == 200

            resp = client.get(f"/api/experiments/{exp_id}/replay/analysis/blast-radius")
            assert resp.status_code == 200
            assert 0.0 <= resp.json()["fraction"] <= 1.0

            resp = client.get(
                f"/api/experiments/{exp_id}/replay/analysis/critical-nodes", params={"top_n": 2}
            )
            assert resp.status_code == 200
            assert len(resp.json()["nodes"]) <= 2

            node_id = graph["nodes"][0]["id"]
            resp = client.get(
                f"/api/experiments/{exp_id}/replay/analysis/provenance",
                params={"node_id": node_id},
            )
            assert resp.status_code == 200
            assert resp.json()["chain"][0] == node_id
    finally:
        asyncio.run(_cleanup(runner.experiment_id))


def test_replay_endpoints_404_for_unknown_experiment():
    with TestClient(app) as client:
        fake_id = uuid.uuid4()
        assert client.get(f"/api/experiments/{fake_id}/replay/graph").status_code == 404
        assert client.get(f"/api/experiments/{fake_id}/replay/metrics").status_code == 404
        assert client.get(f"/api/experiments/{fake_id}/replay/remediation").status_code == 404


def test_replay_endpoints_409_when_experiment_never_finished():
    async def setup() -> uuid.UUID:
        pool = await create_pool(TEST_SETTINGS)
        try:
            exp_id = uuid.uuid4()
            await pool.execute(
                "INSERT INTO experiments (experiment_id, seed, config, app_version, "
                "schema_version) VALUES ($1, $2, $3, 'test', 1)",
                exp_id,
                1,
                json.dumps({"seed": 1, "node_count": 25}),
            )
            return exp_id
        finally:
            await pool.close()

    exp_id = asyncio.run(setup())
    try:
        with TestClient(app) as client:
            resp = client.get(f"/api/experiments/{exp_id}/replay/graph")
            assert resp.status_code == 409
    finally:
        asyncio.run(_cleanup(exp_id))


def test_replay_endpoints_409_for_real_provider_config():
    # A real vLLM run can't actually complete without a reachable endpoint in
    # this environment, so this test only exercises the config-level guard by
    # inserting a finished-looking row directly, mirroring the prior test's
    # approach, rather than trying to run one to completion.
    async def insert_finished_vllm_row() -> uuid.UUID:
        pool = await create_pool(TEST_SETTINGS)
        try:
            exp_id = uuid.uuid4()
            await pool.execute(
                "INSERT INTO experiments (experiment_id, seed, config, app_version, "
                "schema_version, final_sim_tick, final_status) "
                "VALUES ($1, $2, $3, 'test', 1, $4, 'finished')",
                exp_id,
                1,
                json.dumps(
                    {
                        "seed": 1,
                        "node_count": 25,
                        "real_agent_count": 1,
                        "model_provider": "vllm",
                    }
                ),
                3,
            )
            return exp_id
        finally:
            await pool.close()

    exp_id = asyncio.run(insert_finished_vllm_row())
    try:
        with TestClient(app) as client:
            resp = client.get(f"/api/experiments/{exp_id}/replay/metrics")
            assert resp.status_code == 409
    finally:
        asyncio.run(_cleanup(exp_id))
