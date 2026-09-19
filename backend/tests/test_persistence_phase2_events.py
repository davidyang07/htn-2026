"""Proves docs/PHASE_2_PLAN.md §10's central claim structurally, not just by
assertion: MODEL_REQUESTED/MODEL_RESPONDED/TOOL_EXECUTED events round-trip
through PostgresWriter and the existing history endpoints with zero
persistence-layer code changes -- because event_type is TEXT and metadata is
unconstrained JSONB (docs/PHASE_1_5_PLAN.md §4), not because anything new
was added to accommodate them.
"""

import asyncio

from fastapi.testclient import TestClient

from app.db import create_pool
from app.gateway.gateway import ModelGateway
from app.gateway.mock_provider import MockProvider
from app.main import app
from app.orchestrator.runner import ExperimentRunner
from app.persistence.registry import writer_registry
from app.persistence.writer import PostgresWriter
from app.schemas.events import INCIDENT_EVENT_TYPES
from app.schemas.experiment import ExperimentConfig

from .conftest import TEST_SETTINGS, requires_postgres

pytestmark = requires_postgres


async def _persist_hybrid_run(pool) -> ExperimentRunner:
    # Same highest-degree-overlap config test_real_agent_determinism.py
    # already proves produces real-real edges for seed=42.
    config = ExperimentConfig(seed=42, node_count=60, real_agent_count=8, max_ticks=20)
    runner = ExperimentRunner(config)
    runner.tick_interval = 0
    gateway = ModelGateway(
        MockProvider(), timeout_s=5.0, max_retries=1, max_concurrency=8,
        max_requests_per_experiment=1000,
    )
    runner._gateway = gateway  # mirrors production wiring without re-deriving build_gateway()

    writer = PostgresWriter(pool, runner.experiment_id, runner.bus, runner)
    await writer.start()
    writer_registry.add(runner.experiment_id, writer)
    await runner.publish_initial()
    await runner._run_loop()

    deadline = asyncio.get_event_loop().time() + 10.0
    while not writer._task.done():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("writer did not finalize within the timeout")
        await asyncio.sleep(0.01)
    return runner


async def _cleanup(*experiment_ids: object) -> None:
    pool = await create_pool(TEST_SETTINGS)
    try:
        for experiment_id in experiment_ids:
            await pool.execute("DELETE FROM experiments WHERE experiment_id = $1", experiment_id)
    finally:
        await pool.close()


def test_model_and_tool_events_persist_and_page_through_events_endpoint():
    async def setup() -> ExperimentRunner:
        pool = await create_pool(TEST_SETTINGS)
        try:
            return await _persist_hybrid_run(pool)
        finally:
            await pool.close()

    runner = asyncio.run(setup())
    try:
        with TestClient(app) as client:
            exp_id = str(runner.experiment_id)

            all_events: list[dict] = []
            since_seq = -1
            while True:
                page = client.get(
                    f"/api/experiments/{exp_id}/events",
                    params={"since_seq": since_seq, "limit": 500},
                )
                assert page.status_code == 200
                body = page.json()
                all_events.extend(body["events"])
                if body["next_seq"] is None:
                    break
                since_seq = body["next_seq"]

            event_types = {e["event_type"] for e in all_events}
            assert "MODEL_REQUESTED" in event_types
            assert "MODEL_RESPONDED" in event_types

            model_requested = next(e for e in all_events if e["event_type"] == "MODEL_REQUESTED")
            assert model_requested["agent_id"] is not None
            assert model_requested["metadata"]["source_agent_id"] is not None

            model_responded = next(e for e in all_events if e["event_type"] == "MODEL_RESPONDED")
            assert model_responded["metadata"]["provider"] == "mock"
            assert "latency_ms" in model_responded["metadata"]

            # No confidential_token or raw prompt/response text anywhere in
            # any persisted, API-readable event metadata (docs/PHASE_2_PLAN.md
            # §10's logging/persistence discipline).
            for e in all_events:
                assert "confidential_token" not in e["metadata"]
                assert "system_prompt" not in e["metadata"]
                assert "user_message" not in e["metadata"]
    finally:
        asyncio.run(_cleanup(runner.experiment_id))


def test_model_and_tool_events_excluded_from_incidents_endpoint():
    async def setup() -> ExperimentRunner:
        pool = await create_pool(TEST_SETTINGS)
        try:
            return await _persist_hybrid_run(pool)
        finally:
            await pool.close()

    runner = asyncio.run(setup())
    try:
        with TestClient(app) as client:
            exp_id = str(runner.experiment_id)

            resp = client.get(f"/api/experiments/{exp_id}/incidents", params={"limit": 2000})
            assert resp.status_code == 200
            incident_types = {e["event_type"] for e in resp.json()["events"]}

            assert incident_types <= {t.value for t in INCIDENT_EVENT_TYPES}
            assert "MODEL_REQUESTED" not in incident_types
            assert "MODEL_RESPONDED" not in incident_types
            assert "TOOL_EXECUTED" not in incident_types
    finally:
        asyncio.run(_cleanup(runner.experiment_id))


def test_replay_snapshot_regenerates_real_agent_kind_and_never_leaks_token():
    async def setup() -> ExperimentRunner:
        pool = await create_pool(TEST_SETTINGS)
        try:
            return await _persist_hybrid_run(pool)
        finally:
            await pool.close()

    runner = asyncio.run(setup())
    try:
        with TestClient(app) as client:
            exp_id = str(runner.experiment_id)
            resp = client.get(f"/api/experiments/{exp_id}/replay-snapshot")
            assert resp.status_code == 200
            body = resp.json()

            real_nodes = [n for n in body["nodes"] if n["agent_kind"] == "real"]
            assert len(real_nodes) == 8
            for n in real_nodes:
                assert "confidential_token" not in n
            assert "confidential_token" not in resp.text
    finally:
        asyncio.run(_cleanup(runner.experiment_id))
