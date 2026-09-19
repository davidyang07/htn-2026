# AgentShield Continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the seven gaps the user named on top of the current green state (commit `3db28f9`): history/replay parity for security-plane/remediation/comparison metrics, a cross-matrix remediation audit, a hardened CI test gate, stronger LangGraph regression coverage, a polished golden demo, reconciled docs, and a documented (not attempted) typed-node-rendering decision.

**Architecture:** Every new backend capability reuses existing pure functions (`build_security_graph`, `app/metrics/compute.py`, `app/remediation/analyze.py::recommend`) exactly as the live routes in `routes_graph.py` already do — the only new mechanism is a small deterministic re-simulation helper (`app/engine/replay.py`) that reconstructs a persisted experiment's final `WorldState` from `(seed, config, final_sim_tick)`, since world state is already documented as a pure function of those inputs (`docs/PLAN.md` §2.3). No event-log replay, no new persistence, no new dependency. Frontend changes swap the comparison view's thin stream-derived metrics for the same rich `MetricsResponse` both live and historical arms can now fetch over REST.

**Tech Stack:** FastAPI + asyncpg + pydantic (backend), Next.js 16 + TypeScript + vitest (frontend), pytest + ruff (backend tests/lint), existing Makefile targets.

**Spec:** `docs/PLAN.md` (authoritative architecture/roadmap; see §2.3, §2.5, §9 "Next recommended milestone", §10). `docs/SPEC.md` for the underlying deterministic-engine mechanism (unchanged by this plan).

## Global Constraints

- Deterministic engine mechanism (event schema, derived-keyed RNG, fixed-tick engine) is **preserved, not replaced** — every new code path calls existing pure functions (`advance`, `build_world`, `build_security_graph`, `app/metrics/compute.py`, `app/remediation/analyze.py`), never reimplements them.
- No new runtime dependency, backend or frontend.
- No new Postgres migration — `experiments.config` and `experiments.final_sim_tick` (already persisted columns) are sufficient to reconstruct history.
- Implement only what the user's 7 priorities ask for; do not touch `frontend/src/components/NetworkGraph.tsx` (priority 7 stays documented-only, no browser-verification tool available this session — confirmed via `ToolSearch`, matching every prior session's documented decision in `docs/PLAN.md` §9 item 1).
- Postgres must be reachable at `localhost:5432` with an `agentnet_test` database for the new Postgres-backed tests: `docker compose up -d postgres` (already running this session), then `docker exec <container> psql -U agentnet -d agentnet -c "CREATE DATABASE agentnet_test;"` if not already created, then `cd backend && POSTGRES_DB=agentnet_test .venv/bin/python scripts/migrate.py`. Run all backend tests in this plan with `POSTGRES_DB=agentnet_test .venv/bin/pytest` (per `Makefile`'s `test` target) so the previously-skipped Postgres-backed suite actually executes.
- A persisted experiment can only be replayed if `config.real_agent_count == 0` or `config.model_provider == "mock"` — replaying a real-provider (`vllm`) run would silently re-issue real network calls and is not guaranteed deterministic. This is a deliberate, documented limitation (see Task 1), not a bug.
- Every new pure function gets a unit test; every new endpoint gets a `requires_postgres`-marked integration test following `tests/test_history_endpoints.py`'s existing fixture pattern.

---

### Task 1: Deterministic replay reconstruction (`app/engine/replay.py`)

**Files:**
- Create: `backend/app/engine/replay.py`
- Test: `backend/tests/test_engine_replay.py`

**Interfaces:**
- Consumes: `app.engine.topology.build_world(config) -> tuple[WorldState, list[EventDraft]]`, `app.engine.tick.advance(state, config) -> tuple[WorldState, list[EventDraft]]`, `app.engine.propagation.is_finished(state, config) -> bool`, `app.gateway.factory.build_gateway(config, settings, http_client) -> ModelGateway | None`, `app.scenarios.registry.run_async_scenarios(state, config, gateway, tick) -> tuple[WorldState, list[EventDraft]]`, `app.events.emitter.EventEmitter(experiment_id).emit(drafts) -> list[Event]`, `app.config.get_settings() -> Settings`.
- Produces: `reconstruct_final_state(config: ExperimentConfig, target_tick: int) -> tuple[WorldState, list[Event]]` and `class ReplayUnsupportedError(Exception)` — both consumed by Task 2's routes.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_engine_replay.py
import pytest

from app.engine.replay import ReplayUnsupportedError, reconstruct_final_state
from app.engine.tick import advance
from app.engine.topology import build_world
from app.schemas.experiment import ExperimentConfig


def test_reconstruct_final_state_matches_manual_advance_to_the_same_tick():
    config = ExperimentConfig(seed=7, node_count=30, p_same=0.3, max_ticks=10)
    world, _ = build_world(config)
    for _ in range(4):
        world, _ = advance(world, config)

    reconstructed, _ = reconstruct_final_state(config, target_tick=4)

    assert reconstructed.tick == world.tick == 4
    assert {n: s.security_state for n, s in reconstructed.nodes.items()} == {
        n: s.security_state for n, s in world.nodes.items()
    }


def test_reconstruct_final_state_stops_at_target_tick_even_if_not_yet_finished():
    config = ExperimentConfig(seed=7, node_count=30, p_same=0.3, max_ticks=200)
    reconstructed, _ = reconstruct_final_state(config, target_tick=2)
    assert reconstructed.tick == 2


def test_reconstruct_final_state_is_deterministic():
    config = ExperimentConfig(seed=11, node_count=25, p_same=0.2, max_ticks=50)
    world1, events1 = reconstruct_final_state(config, target_tick=8)
    world2, events2 = reconstruct_final_state(config, target_tick=8)
    assert {n: s.security_state for n, s in world1.nodes.items()} == {
        n: s.security_state for n, s in world2.nodes.items()
    }
    assert [e.event_type for e in events1] == [e.event_type for e in events2]


def test_reconstruct_final_state_returns_events_with_matching_experiment_id():
    config = ExperimentConfig(seed=3, node_count=25, max_ticks=3)
    _, events = reconstruct_final_state(config, target_tick=2)
    ids = {e.experiment_id for e in events}
    assert len(ids) == 1


def test_reconstruct_final_state_rejects_real_provider():
    config = ExperimentConfig(
        seed=1, node_count=25, real_agent_count=2, model_provider="vllm", max_ticks=3
    )
    with pytest.raises(ReplayUnsupportedError):
        reconstruct_final_state(config, target_tick=2)


def test_reconstruct_final_state_supports_mock_provider_with_real_agents():
    config = ExperimentConfig(
        seed=5,
        node_count=25,
        real_agent_count=3,
        model_provider="mock",
        active_scenarios=["propagation", "prompt_injection"],
        max_ticks=4,
    )
    world, events = reconstruct_final_state(config, target_tick=3)
    assert world.tick == 3
    assert events
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_engine_replay.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.replay'`

- [ ] **Step 3: Implement `app/engine/replay.py`**

```python
"""Reconstructs a persisted experiment's final WorldState by re-running the
deterministic engine from (seed, config) up to a target tick, rather than
reading the event log back. World state is already a pure function of
(seed, config) (docs/PLAN.md §2.3), and `experiments.final_sim_tick` is
already persisted (app/persistence/writer.py) -- so bounding the loop by
that tick, instead of always running to natural completion like
app/engine/simulate.py::simulate does, reconstructs the exact historical
final state whether the run finished naturally or was stopped early.
Mirrors app/orchestrator/runner.py's own per-tick loop (advance(), then
run_async_scenarios() when a gateway exists) so live and replayed state
can never diverge in how a tick is computed.

A real model provider (model_provider != "mock") is deliberately refused:
replaying it would either silently re-issue real network calls or (with no
reachable endpoint) fail outright, and a real LLM's output is not
guaranteed reproducible even with the same seed -- unlike MockProvider,
which this codebase already relies on for all deterministic replay/
benchmark work.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import httpx

from app.config import get_settings
from app.engine.propagation import is_finished
from app.engine.state import WorldState
from app.engine.tick import advance
from app.engine.topology import build_world
from app.events.emitter import EventEmitter
from app.gateway.factory import build_gateway
from app.scenarios.registry import run_async_scenarios
from app.schemas.events import Event, EventDraft, EventType
from app.schemas.experiment import ExperimentConfig


class ReplayUnsupportedError(Exception):
    """Raised when a persisted experiment's config cannot be safely replayed."""


def _uses_async_scenario(config: ExperimentConfig) -> bool:
    return config.real_agent_count > 0


def _should_continue(state: WorldState, config: ExperimentConfig, target_tick: int) -> bool:
    if state.tick >= target_tick:
        return False
    return not is_finished(state, config)


def _reconstruct_sync(
    config: ExperimentConfig, target_tick: int
) -> tuple[WorldState, list[EventDraft]]:
    drafts: list[EventDraft] = [EventDraft(sim_tick=0, event_type=EventType.EXPERIMENT_STARTED)]
    world, topology_drafts = build_world(config)
    drafts.extend(topology_drafts)
    while _should_continue(world, config, target_tick):
        world, tick_drafts = advance(world, config)
        drafts.extend(tick_drafts)
    return world, drafts


async def _reconstruct_async(
    config: ExperimentConfig, target_tick: int
) -> tuple[WorldState, list[EventDraft]]:
    async with httpx.AsyncClient() as http_client:
        gateway = build_gateway(config, get_settings(), http_client)
        assert gateway is not None  # real_agent_count > 0 is this function's only caller path

        drafts: list[EventDraft] = [
            EventDraft(sim_tick=0, event_type=EventType.EXPERIMENT_STARTED)
        ]
        state, topology_drafts = build_world(config)
        drafts.extend(topology_drafts)
        while _should_continue(state, config, target_tick):
            state, tick_drafts = advance(state, config)
            state, async_drafts = await run_async_scenarios(
                state, config, gateway, tick=state.tick
            )
            drafts.extend([*tick_drafts, *async_drafts])
    return state, drafts


def reconstruct_final_state(
    config: ExperimentConfig, target_tick: int
) -> tuple[WorldState, list[Event]]:
    if config.real_agent_count > 0 and config.model_provider != "mock":
        raise ReplayUnsupportedError(
            "replay reconstruction only supports model_provider='mock' -- a real "
            "provider run is not deterministically reproducible and replay must "
            "never silently re-issue real API calls"
        )

    if _uses_async_scenario(config):
        world, drafts = asyncio.run(_reconstruct_async(config, target_tick))
    else:
        world, drafts = _reconstruct_sync(config, target_tick)

    events = EventEmitter(experiment_id=uuid4()).emit(drafts)
    return world, events
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_engine_replay.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Full backend regression + determinism check**

Run: `cd backend && POSTGRES_DB=agentnet_test .venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/python scripts/verify_determinism.py`
Expected: all pass, zero ruff findings

- [ ] **Step 6: Commit**

```bash
git add backend/app/engine/replay.py backend/tests/test_engine_replay.py
git commit -m "feat(engine): add deterministic replay reconstruction from (config, final_sim_tick)"
```

---

### Task 2: History/replay REST endpoints

**Files:**
- Modify: `backend/app/api/routes_history.py`
- Test: `backend/tests/test_history_endpoints.py`

**Interfaces:**
- Consumes: Task 1's `reconstruct_final_state(config, target_tick) -> tuple[WorldState, list[Event]]` / `ReplayUnsupportedError`; existing `build_security_graph(state, config) -> SecurityGraph` (`app/graph/builder.py`); `attack_paths`, `blast_radius`, `critical_nodes`, `provenance` (`app/graph/analysis.py`); `app.metrics.compute` module; `app.remediation.analyze.recommend`; existing schemas `SecurityGraphView`, `GraphNodeView`, `GraphEdgeView`, `AttackPathsResponse`, `BlastRadiusResponse`, `CriticalNodesResponse`, `CriticalNodeView`, `ProvenanceResponse`, `MetricsResponse`, `RemediationResponse`, `RecommendationView` (all already defined, imported the same way `routes_graph.py` does).
- Produces: seven new routes under the existing `router = APIRouter(prefix="/api/experiments", tags=["history"])`:
  - `GET /{experiment_id}/replay/graph` → `SecurityGraphView`
  - `GET /{experiment_id}/replay/analysis/attack-paths?source&target` → `AttackPathsResponse`
  - `GET /{experiment_id}/replay/analysis/blast-radius` → `BlastRadiusResponse`
  - `GET /{experiment_id}/replay/analysis/critical-nodes?top_n` → `CriticalNodesResponse`
  - `GET /{experiment_id}/replay/analysis/provenance?node_id` → `ProvenanceResponse`
  - `GET /{experiment_id}/replay/metrics` → `MetricsResponse`
  - `GET /{experiment_id}/replay/remediation` → `RemediationResponse`
  All 404 for an unknown experiment, 409 if `final_sim_tick IS NULL` (never finished) or the config is replay-unsupported (real provider), 503 if Postgres unavailable (same `_get_pool` as every other route in this file).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_history_endpoints.py` (reuses `_persist_completed_run`/`_cleanup`/`requires_postgres` already in this file):

```python
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
            asyncio.run(live._run_loop())
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
```

Add the needed imports at the top of the test file: `import json` (if not already imported) and `from app.schemas.experiment import ExperimentConfig` (if not already imported) — check the file's existing import block first and only add what's missing.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && POSTGRES_DB=agentnet_test .venv/bin/pytest tests/test_history_endpoints.py -v`
Expected: FAIL with 404s on the new `/replay/...` paths (routes don't exist yet)

- [ ] **Step 3: Implement the routes in `routes_history.py`**

Add these imports to the existing import block:

```python
from app.engine.replay import ReplayUnsupportedError, reconstruct_final_state
from app.graph.analysis import attack_paths, blast_radius, critical_nodes, provenance
from app.graph.builder import build_security_graph
from app.graph.types import NodeType
from app.metrics import compute as metrics
from app.remediation.analyze import recommend
from app.schemas.graph import (
    AttackPathsResponse,
    BlastRadiusResponse,
    CriticalNodesResponse,
    CriticalNodeView,
    GraphEdgeView,
    GraphNodeView,
    ProvenanceResponse,
    SecurityGraphView,
)
from app.schemas.metrics import MetricsResponse
from app.schemas.remediation import RecommendationView, RemediationResponse
```

Add this helper near `_require_experiment_exists` and this block of routes at the end of the file:

```python
async def _load_replay_target(
    pool: asyncpg.Pool, experiment_id: UUID
) -> tuple[ExperimentConfig, int]:
    row = await pool.fetchrow(
        "SELECT config, final_sim_tick FROM experiments WHERE experiment_id = $1",
        experiment_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if row["final_sim_tick"] is None:
        raise HTTPException(
            status_code=409, detail="experiment has not finished; no final tick recorded yet"
        )
    return ExperimentConfig(**json.loads(row["config"])), row["final_sim_tick"]


async def _reconstruct_for_replay(pool: asyncpg.Pool, experiment_id: UUID):
    config, target_tick = await _load_replay_target(pool, experiment_id)
    try:
        world, events = reconstruct_final_state(config, target_tick)
    except ReplayUnsupportedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    graph = build_security_graph(world, config)
    return world, config, graph, events


@router.get("/{experiment_id}/replay/graph", response_model=SecurityGraphView)
async def get_replay_graph(experiment_id: UUID, request: Request) -> SecurityGraphView:
    pool = _get_pool(request)
    _, _, graph, _ = await _reconstruct_for_replay(pool, experiment_id)
    return SecurityGraphView(
        nodes=[
            GraphNodeView(
                id=n.id, node_type=n.node_type, security_state=n.security_state, attrs=n.attrs
            )
            for n in graph.nodes
        ],
        edges=[
            GraphEdgeView(source=e.source, target=e.target, edge_type=e.edge_type, attrs=e.attrs)
            for e in graph.edges()
        ],
    )


@router.get(
    "/{experiment_id}/replay/analysis/attack-paths", response_model=AttackPathsResponse
)
async def get_replay_attack_paths(
    experiment_id: UUID, request: Request, source: str, target: str
) -> AttackPathsResponse:
    pool = _get_pool(request)
    _, _, graph, _ = await _reconstruct_for_replay(pool, experiment_id)
    return AttackPathsResponse(paths=attack_paths(graph, source, target))


@router.get(
    "/{experiment_id}/replay/analysis/blast-radius", response_model=BlastRadiusResponse
)
async def get_replay_blast_radius(experiment_id: UUID, request: Request) -> BlastRadiusResponse:
    pool = _get_pool(request)
    _, _, graph, _ = await _reconstruct_for_replay(pool, experiment_id)
    compromised = sorted(graph.compromised_ids())
    reachable = sorted(blast_radius(graph))
    total_agents = len(graph.nodes_of_type(NodeType.AGENT))
    fraction = (len(reachable) / total_agents) if total_agents else 0.0
    return BlastRadiusResponse(compromised=compromised, reachable=reachable, fraction=fraction)


@router.get(
    "/{experiment_id}/replay/analysis/critical-nodes", response_model=CriticalNodesResponse
)
async def get_replay_critical_nodes(
    experiment_id: UUID, request: Request, top_n: int = 5
) -> CriticalNodesResponse:
    pool = _get_pool(request)
    _, _, graph, _ = await _reconstruct_for_replay(pool, experiment_id)
    ranked = critical_nodes(graph, top_n=top_n)
    return CriticalNodesResponse(
        nodes=[CriticalNodeView(id=node_id, betweenness=score) for node_id, score in ranked]
    )


@router.get(
    "/{experiment_id}/replay/analysis/provenance", response_model=ProvenanceResponse
)
async def get_replay_provenance(
    experiment_id: UUID, request: Request, node_id: str
) -> ProvenanceResponse:
    pool = _get_pool(request)
    world, _, _, _ = await _reconstruct_for_replay(pool, experiment_id)
    if node_id not in world.nodes:
        raise HTTPException(status_code=404, detail="node not found in this experiment")
    compromised_by = {n.id: n.compromised_by for n in world.nodes.values()}
    return ProvenanceResponse(chain=provenance(compromised_by, node_id))


@router.get("/{experiment_id}/replay/metrics", response_model=MetricsResponse)
async def get_replay_metrics(experiment_id: UUID, request: Request) -> MetricsResponse:
    pool = _get_pool(request)
    world, _, graph, events = await _reconstruct_for_replay(pool, experiment_id)
    return MetricsResponse(
        compromise_fraction=metrics.compromise_fraction(world),
        retained_utility=metrics.retained_utility(world),
        blast_radius_fraction=metrics.blast_radius_fraction(graph),
        privileged_exposure=metrics.privileged_exposure(graph),
        security_plane_integrity=metrics.security_plane_integrity(graph),
        attack_success_rate=metrics.attack_success_rate(events),
        false_quarantine_rate=metrics.false_quarantine_rate(events),
        detection_latency=metrics.detection_latency(world, events),
        containment_latency=metrics.containment_latency(events),
    )


@router.get("/{experiment_id}/replay/remediation", response_model=RemediationResponse)
async def get_replay_remediation(experiment_id: UUID, request: Request) -> RemediationResponse:
    pool = _get_pool(request)
    world, config, graph, _ = await _reconstruct_for_replay(pool, experiment_id)
    fraction = metrics.compromise_fraction(world)
    integrity = metrics.security_plane_integrity(graph)
    recommendations = recommend(config, fraction, integrity)
    return RemediationResponse(
        recommendations=[
            RecommendationView(description=r.description, config_diff=r.config_diff)
            for r in recommendations
        ]
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && POSTGRES_DB=agentnet_test .venv/bin/pytest tests/test_history_endpoints.py -v`
Expected: PASS (all tests in the file, old and new)

- [ ] **Step 5: Full backend regression + ruff + determinism**

Run: `cd backend && POSTGRES_DB=agentnet_test .venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/python scripts/verify_determinism.py`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes_history.py backend/tests/test_history_endpoints.py
git commit -m "feat(api): add history/replay equivalents of graph, analysis, metrics, remediation"
```

---

### Task 3: Frontend replay API client + schema regeneration

**Files:**
- Modify: `frontend/src/lib/api/client.ts`
- Modify: `frontend/src/lib/api/client.test.ts`
- Modify (generated): `frontend/src/lib/api/schema.d.ts`

**Interfaces:**
- Consumes: Task 2's seven new backend routes.
- Produces: `getReplaySecurityGraph`, `getReplayAttackPaths`, `getReplayBlastRadius`, `getReplayCriticalNodes`, `getReplayProvenance`, `getReplayMetrics`, `getReplayRemediation` — same parameter/return shapes as their live counterparts (`SecurityGraphView`, `AttackPathsResponse`, `BlastRadiusResponse`, `CriticalNodesResponse`, `ProvenanceResponse`, `MetricsResponse`, `RemediationResponse`, all already imported in this file) — consumed by Task 4 and Task 5.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/lib/api/client.test.ts`, mirroring the existing `getSecurityGraph`/`getAttackPaths`/etc. tests just above (same `mockFetch`/`parsed` helper pattern already in this file):

```ts
it("getReplaySecurityGraph GETs /api/experiments/{id}/replay/graph", async () => {
  const fetchMock = mockFetch({ nodes: [], edges: [] });
  await getReplaySecurityGraph("a");
  const url = fetchMock.mock.calls[0][0];
  expect(String(url)).toMatch(/\/api\/experiments\/a\/replay\/graph$/);
});

it("getReplayAttackPaths GETs .../replay/analysis/attack-paths with source/target params", async () => {
  const fetchMock = mockFetch({ paths: [] });
  await getReplayAttackPaths("a", "n1", "n2");
  const parsed = new URL(fetchMock.mock.calls[0][0] as string);
  expect(parsed.pathname).toBe("/api/experiments/a/replay/analysis/attack-paths");
  expect(parsed.searchParams.get("source")).toBe("n1");
  expect(parsed.searchParams.get("target")).toBe("n2");
});

it("getReplayBlastRadius GETs .../replay/analysis/blast-radius", async () => {
  const fetchMock = mockFetch({ compromised: [], reachable: [], fraction: 0 });
  await getReplayBlastRadius("a");
  const url = fetchMock.mock.calls[0][0];
  expect(String(url)).toMatch(/\/api\/experiments\/a\/replay\/analysis\/blast-radius$/);
});

it("getReplayCriticalNodes GETs .../replay/analysis/critical-nodes with an optional top_n param", async () => {
  const fetchMock = mockFetch({ nodes: [] });
  await getReplayCriticalNodes("a", 3);
  const parsed = new URL(fetchMock.mock.calls[0][0] as string);
  expect(parsed.pathname).toBe("/api/experiments/a/replay/analysis/critical-nodes");
  expect(parsed.searchParams.get("top_n")).toBe("3");
});

it("getReplayProvenance GETs .../replay/analysis/provenance with a node_id param", async () => {
  const fetchMock = mockFetch({ chain: [] });
  await getReplayProvenance("a", "agent-000");
  const parsed = new URL(fetchMock.mock.calls[0][0] as string);
  expect(parsed.pathname).toBe("/api/experiments/a/replay/analysis/provenance");
  expect(parsed.searchParams.get("node_id")).toBe("agent-000");
});

it("getReplayMetrics GETs .../replay/metrics", async () => {
  const fetchMock = mockFetch({
    compromise_fraction: 0,
    retained_utility: 1,
    blast_radius_fraction: 0,
    privileged_exposure: 0,
    security_plane_integrity: 1,
    attack_success_rate: 0,
    false_quarantine_rate: 0,
    detection_latency: null,
    containment_latency: null,
  });
  await getReplayMetrics("a");
  const url = fetchMock.mock.calls[0][0];
  expect(String(url)).toMatch(/\/api\/experiments\/a\/replay\/metrics$/);
});

it("getReplayRemediation GETs .../replay/remediation", async () => {
  const fetchMock = mockFetch({ recommendations: [] });
  await getReplayRemediation("a");
  const url = fetchMock.mock.calls[0][0];
  expect(String(url)).toMatch(/\/api\/experiments\/a\/replay\/remediation$/);
});
```

Check this test file's existing top-of-file import list and `mockFetch` helper definition first — add the seven new function names to the existing `import { ... } from "./client"` block (do not duplicate the `mockFetch` helper; reuse it exactly as the existing tests above do).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npm test -- client.test.ts`
Expected: FAIL with `getReplaySecurityGraph is not a function` (or a TypeScript error naming the missing exports)

- [ ] **Step 3: Implement the client functions**

Append to `frontend/src/lib/api/client.ts`, directly after the existing `getRemediation` function:

```ts
// History/replay equivalents of the security-graph/analysis/metrics/
// remediation endpoints above (docs/PLAN.md §9's "Next recommended
// milestone") -- same response shapes, backed by a persisted experiment's
// reconstructed final state instead of a live in-memory runner.

export async function getReplaySecurityGraph(experimentId: string): Promise<SecurityGraphView> {
  const res = await fetch(`${BACKEND_URL}/api/experiments/${experimentId}/replay/graph`);
  if (!res.ok) {
    throw new Error(`failed to get replay security graph: ${res.status}`);
  }
  return res.json();
}

export async function getReplayAttackPaths(
  experimentId: string,
  source: string,
  target: string,
): Promise<AttackPathsResponse> {
  const url = new URL(
    `${BACKEND_URL}/api/experiments/${experimentId}/replay/analysis/attack-paths`,
  );
  url.searchParams.set("source", source);
  url.searchParams.set("target", target);
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`failed to get replay attack paths: ${res.status}`);
  }
  return res.json();
}

export async function getReplayBlastRadius(experimentId: string): Promise<BlastRadiusResponse> {
  const res = await fetch(
    `${BACKEND_URL}/api/experiments/${experimentId}/replay/analysis/blast-radius`,
  );
  if (!res.ok) {
    throw new Error(`failed to get replay blast radius: ${res.status}`);
  }
  return res.json();
}

export async function getReplayCriticalNodes(
  experimentId: string,
  topN?: number,
): Promise<CriticalNodesResponse> {
  const url = new URL(
    `${BACKEND_URL}/api/experiments/${experimentId}/replay/analysis/critical-nodes`,
  );
  if (topN !== undefined) url.searchParams.set("top_n", String(topN));
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`failed to get replay critical nodes: ${res.status}`);
  }
  return res.json();
}

export async function getReplayProvenance(
  experimentId: string,
  nodeId: string,
): Promise<ProvenanceResponse> {
  const url = new URL(
    `${BACKEND_URL}/api/experiments/${experimentId}/replay/analysis/provenance`,
  );
  url.searchParams.set("node_id", nodeId);
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`failed to get replay provenance: ${res.status}`);
  }
  return res.json();
}

export async function getReplayMetrics(experimentId: string): Promise<MetricsResponse> {
  const res = await fetch(`${BACKEND_URL}/api/experiments/${experimentId}/replay/metrics`);
  if (!res.ok) {
    throw new Error(`failed to get replay metrics: ${res.status}`);
  }
  return res.json();
}

export async function getReplayRemediation(
  experimentId: string,
): Promise<RemediationResponse> {
  const res = await fetch(`${BACKEND_URL}/api/experiments/${experimentId}/replay/remediation`);
  if (!res.ok) {
    throw new Error(`failed to get replay remediation: ${res.status}`);
  }
  return res.json();
}
```

Also delete the now-stale comment above `getSecurityGraph` that reads `// ... history/replay equivalents are not yet built (docs/PLAN.md §9).` — replace it with `// History/replay equivalents are defined further down this file.`

- [ ] **Step 4: Regenerate the OpenAPI schema and run tests**

Run (backend must be running — start it first with `cd backend && POSTGRES_DB=agentnet_test .venv/bin/uvicorn app.main:app &`, wait for it to be up, then):
```bash
cd frontend && npx openapi-typescript http://localhost:8000/openapi.json -o src/lib/api/schema.d.ts
npm test -- client.test.ts
npx tsc --noEmit
```
Expected: `schema.d.ts` diff shows the seven new `/replay/...` paths added; `client.test.ts` passes; `tsc` clean. Stop the background uvicorn afterward.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api/client.ts frontend/src/lib/api/client.test.ts frontend/src/lib/api/schema.d.ts
git commit -m "feat(frontend): add API client functions for history/replay endpoints"
```

---

### Task 4: SecurityInsightsPanel replay mode + wire into the replay page

**Files:**
- Modify: `frontend/src/components/SecurityInsightsPanel.tsx`
- Modify: `frontend/src/app/history/[id]/page.tsx`

**Interfaces:**
- Consumes: Task 3's `getReplaySecurityGraph`, `getReplayCriticalNodes`, `getReplayRemediation`, `getReplayMetrics`, `getReplayProvenance`.
- Produces: `SecurityInsightsPanel({ experimentId, mode = "live" }: { experimentId: string; mode?: "live" | "replay" })` — `mode="replay"` fetches once (no polling, since a persisted run's reconstructed state never changes) and shows the same dl/panels as the live mode.

- [ ] **Step 1: Modify `SecurityInsightsPanel.tsx`**

Change the import block to also pull in the four replay functions:

```ts
import {
  getCriticalNodes,
  getMetrics,
  getProvenance,
  getRemediation,
  getReplayCriticalNodes,
  getReplayMetrics,
  getReplayProvenance,
  getReplayRemediation,
  getReplaySecurityGraph,
  getSecurityGraph,
  type CriticalNodeView,
  type MetricsResponse,
  type RemediationResponse,
  type SecurityGraphView,
} from "@/lib/api/client";
```

Change the component signature and its polling effect:

```tsx
export function SecurityInsightsPanel({
  experimentId,
  mode = "live",
}: {
  experimentId: string;
  mode?: "live" | "replay";
}) {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [graph, setGraph] = useState<SecurityGraphView | null>(null);
  const [criticalNodes, setCriticalNodes] = useState<CriticalNodeView[]>([]);
  const [remediation, setRemediation] = useState<RemediationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [provenanceNodeId, setProvenanceNodeId] = useState("");
  const [provenanceChain, setProvenanceChain] = useState<string[] | null>(null);
  const [provenanceError, setProvenanceError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const fetchOnce = () =>
      mode === "live"
        ? Promise.all([
            getMetrics(experimentId),
            getSecurityGraph(experimentId),
            getCriticalNodes(experimentId, 3),
            getRemediation(experimentId),
          ])
        : Promise.all([
            getReplayMetrics(experimentId),
            getReplaySecurityGraph(experimentId),
            getReplayCriticalNodes(experimentId, 3),
            getReplayRemediation(experimentId),
          ]);

    const poll = () => {
      fetchOnce()
        .then(([metricsResp, graphResp, criticalResp, remediationResp]) => {
          if (cancelled) return;
          setMetrics(metricsResp);
          setGraph(graphResp);
          setCriticalNodes(criticalResp.nodes);
          setRemediation(remediationResp);
          setError(null);
        })
        .catch((err) => {
          if (cancelled) return;
          setError(err instanceof Error ? err.message : String(err));
        })
        .finally(() => {
          // A replayed run's reconstructed state is static -- polling again
          // would just refetch the exact same answer forever.
          if (!cancelled && mode === "live") timer = setTimeout(poll, POLL_INTERVAL_MS);
        });
    };
    poll();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [experimentId, mode]);

  const nonAgentSummary = graph ? summarizeNonAgentNodes(graph) : [];

  const lookupProvenance = () => {
    if (!provenanceNodeId.trim()) return;
    (mode === "live"
      ? getProvenance(experimentId, provenanceNodeId.trim())
      : getReplayProvenance(experimentId, provenanceNodeId.trim())
    )
      .then((resp) => {
        setProvenanceChain(resp.chain);
        setProvenanceError(null);
      })
      .catch((err) => {
        setProvenanceChain(null);
        setProvenanceError(err instanceof Error ? err.message : String(err));
      });
  };
```

The rest of the component (the returned JSX) is unchanged.

- [ ] **Step 2: Wire it into the replay page**

In `frontend/src/app/history/[id]/page.tsx`, add the import:

```tsx
import { SecurityInsightsPanel } from "@/components/SecurityInsightsPanel";
```

Change the render block (mirrors `app/page.tsx`'s own `<NetworkGraph /><SecurityInsightsPanel /></>` sibling layout):

```tsx
      <div className="flex flex-1 overflow-visible">
        <MetricsPanel state={state} />
        <section className="min-h-[260px] flex-1 overflow-hidden">
          <NetworkGraph state={state} onNodeClick={setSelectedAgentId} />
        </section>
        <SecurityInsightsPanel experimentId={experimentId} mode="replay" />
      </div>
```

- [ ] **Step 3: Verify**

Run: `cd frontend && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build`
Expected: all pass, zero new warnings. This component has no jsdom/render-based test (this codebase's existing, deliberate convention — see `SecurityInsightsPanel.test.ts`'s own docstring-equivalent comment), so the `mode` branch itself is verified via a dev-server smoke test: `cd backend && POSTGRES_DB=agentnet_test .venv/bin/uvicorn app.main:app &`, `cd frontend && npm run dev &`, create an experiment via the dashboard, let it finish, navigate to `/history`, open its replay page, and confirm the security-insights panel renders with real numbers and no console error. Stop both dev servers afterward.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SecurityInsightsPanel.tsx frontend/src/app/history/\[id\]/page.tsx
git commit -m "feat(frontend): show security-plane/remediation insights on the replay page"
```

---

### Task 5: Comparison view rich-metrics parity

**Files:**
- Modify: `frontend/src/lib/comparison/runToCompletion.ts`
- Modify: `frontend/src/lib/comparison/runToCompletion.test.ts`
- Modify: `frontend/src/lib/comparison/loadHistoricalArm.ts`
- Modify: `frontend/src/lib/comparison/loadHistoricalArm.test.ts`
- Modify: `frontend/src/lib/comparison/useComparison.ts`
- Modify: `frontend/src/components/ComparisonView.tsx`

**Interfaces:**
- Consumes: existing `getMetrics` (live), Task 3's `getReplayMetrics`, existing `getExperimentDetail`.
- Produces: `RunResult.metrics: MetricsResponse` (was `ReturnType<typeof selectMetrics>`), `HistoricalArmResult.metrics: MetricsResponse` (same change), `ArmState.metrics: MetricsResponse` — both `runToCompletion.ts` and `loadHistoricalArm.ts` now return the exact same shape, so `ComparisonView.tsx` renders identical fields for both arms regardless of which one ran live vs. was loaded from history.

- [ ] **Step 1: Update `runToCompletion.ts`'s test first**

In `frontend/src/lib/comparison/runToCompletion.test.ts`, find the assertion(s) on the returned `metrics` shape (they currently check fields like `total`/`healthy`/`compromised`) and change them to assert the rich shape instead, e.g.:

```ts
expect(result.metrics).toMatchObject({
  compromise_fraction: expect.any(Number),
  retained_utility: expect.any(Number),
  blast_radius_fraction: expect.any(Number),
  privileged_exposure: expect.any(Number),
  security_plane_integrity: expect.any(Number),
  attack_success_rate: expect.any(Number),
  false_quarantine_rate: expect.any(Number),
});
```

Also find wherever this test file mocks `getExperiment`/`createExperiment`/WebSocket and add a mock for `getMetrics` returning a fixed `MetricsResponse` object, following this file's existing mocking convention for the other client functions it already mocks.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npm test -- runToCompletion.test.ts`
Expected: FAIL (current code returns the old `selectMetrics` shape, and `getMetrics` isn't called yet)

- [ ] **Step 3: Implement in `runToCompletion.ts`**

Change the import line to add `getMetrics` and the `MetricsResponse` type:

```ts
import {
  createExperiment,
  getExperiment,
  getMetrics,
  stopExperiment,
  backendWsUrl,
  type ExperimentConfig,
  type MetricsResponse,
} from "@/lib/api/client";
```

Change `RunResult`'s type and the tail of `runExperimentToCompletion`:

```ts
export type RunResult = {
  experimentId: string;
  metrics: MetricsResponse;
};
```

```ts
  ws.close();
  // The rich MetricsResponse (security-plane/remediation-relevant fields)
  // is fetched over REST rather than derived from selectMetrics(graphState)
  // -- the same live /metrics endpoint SecurityInsightsPanel already polls
  // -- so a live comparison arm and a historical one (loadHistoricalArm.ts)
  // report the exact same metric shape (docs/PLAN.md §9's "Next
  // recommended milestone"). Fetched before stopExperiment so the runner
  // is still registered.
  const metrics = await getMetrics(experimentId);
  await stopExperiment(experimentId).catch(() => {});
  return { experimentId, metrics };
```

Remove the now-unused `selectMetrics`/`GraphState` import if `graphState`/`reduce` are still needed elsewhere in this file for WS handling (they are — `reduce`/`initialGraphState`/`GraphState`/`StreamFrame` stay; only `selectMetrics` becomes unused and should be dropped from the import list).

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npm test -- runToCompletion.test.ts`
Expected: PASS

- [ ] **Step 5: Update `loadHistoricalArm.ts` and its test**

Write the failing test first in `frontend/src/lib/comparison/loadHistoricalArm.test.ts` — replace assertions on the old `selectMetrics`-shaped result with the `MetricsResponse` shape (same `toMatchObject` block as Step 1), and mock `getReplayMetrics`/`getExperimentDetail` instead of `loadReplayData`/`foldEvents` (check this test file's existing mock setup for `loadReplayData` and replace it).

Run: `cd frontend && npm test -- loadHistoricalArm.test.ts` — expect FAIL.

Implement:

```ts
import { getExperimentDetail, getReplayMetrics } from "@/lib/api/client";

export type HistoricalArmResult = {
  experimentId: string;
  metrics: Awaited<ReturnType<typeof getReplayMetrics>>;
  incomplete: boolean;
};

/**
 * Direct sibling of runToCompletion.ts for a *historical* arm: fetches the
 * same rich MetricsResponse a live arm now fetches (docs/PLAN.md §9's "Next
 * recommended milestone"), via the /replay/metrics endpoint added in
 * app/api/routes_history.py -- no client-side event-log fold needed, since
 * that endpoint already reconstructs the persisted run's final state
 * server-side (app/engine/replay.py). `incomplete` is read directly from
 * the experiment's `is_complete` column (the exact same source
 * loadReplayData's own `incomplete` flag already used).
 */
export async function loadHistoricalArm(experimentId: string): Promise<HistoricalArmResult> {
  const [metrics, detail] = await Promise.all([
    getReplayMetrics(experimentId),
    getExperimentDetail(experimentId),
  ]);
  return { experimentId, metrics, incomplete: detail.is_complete !== true };
}
```

Run: `cd frontend && npm test -- loadHistoricalArm.test.ts` — expect PASS.

- [ ] **Step 6: Update `useComparison.ts`'s types**

Change the `ArmResult`/`ArmState` type definitions to use `MetricsResponse` instead of `ReturnType<typeof selectMetrics>`:

```ts
import type { ExperimentConfig, MetricsResponse } from "@/lib/api/client";

export type ArmResult = { metrics: MetricsResponse; incomplete?: boolean } | { error: string };

export type ArmState = {
  status: "idle" | "running" | "done" | "error";
  metrics?: MetricsResponse;
  error?: string;
  incomplete?: boolean;
};
```

Remove the now-unused `import type { selectMetrics } from "@/lib/stream/reducer";` line.

Run: `cd frontend && npm test -- useComparison.test.ts` — this file mocks `runToCompletion`/`loadHistoricalArm`'s return shapes; update any mock metrics objects there from the old shape to a `MetricsResponse`-shaped object (same fields as Step 1's `toMatchObject`), then re-run to confirm it passes.

- [ ] **Step 7: Update `ComparisonView.tsx`'s `ArmPanel`**

Replace the `<dl>` block's fields (reusing `formatPercent`/`formatLatency` from `SecurityInsightsPanel.tsx`, matching how that panel already renders the same `MetricsResponse` shape):

```tsx
import { formatLatency, formatPercent } from "@/components/SecurityInsightsPanel";
```

```tsx
      {arm.status === "done" && arm.metrics && (
        <dl className="space-y-1 text-slate-400">
          <div className="flex justify-between">
            <dt>Compromise fraction</dt>
            <dd className="font-mono">{formatPercent(arm.metrics.compromise_fraction)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Retained utility</dt>
            <dd className="font-mono">{formatPercent(arm.metrics.retained_utility)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Blast radius</dt>
            <dd className="font-mono">{formatPercent(arm.metrics.blast_radius_fraction)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Privileged exposure</dt>
            <dd className="font-mono">{arm.metrics.privileged_exposure}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Security-plane integrity</dt>
            <dd className="font-mono">{formatPercent(arm.metrics.security_plane_integrity)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Attack success rate</dt>
            <dd className="font-mono">{formatPercent(arm.metrics.attack_success_rate)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>False quarantine rate</dt>
            <dd className="font-mono">{formatPercent(arm.metrics.false_quarantine_rate)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Detection latency</dt>
            <dd className="font-mono">{formatLatency(arm.metrics.detection_latency)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Containment latency</dt>
            <dd className="font-mono">{formatLatency(arm.metrics.containment_latency)}</dd>
          </div>
        </dl>
      )}
```

- [ ] **Step 8: Full frontend verification**

Run: `cd frontend && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/comparison frontend/src/components/ComparisonView.tsx
git commit -m "feat(frontend): give live and historical comparison arms the same rich metrics"
```

---

### Task 6: Cross-matrix remediation audit (priority 2)

**Files:**
- Create: `backend/app/benchmark/audit.py`
- Create: `backend/scripts/run_benchmark_audit.py`
- Modify: `backend/Makefile` reference — add a `benchmark-audit` target to `/home/danda/projects/agentNet/Makefile`
- Test: `backend/tests/test_benchmark_audit.py`

**Interfaces:**
- Consumes: `app.benchmark.matrix.ATTACK_SCENARIOS`, `DEFENSE_BASE_ATTACK`, `DEFENSE_VARIANTS` (all already defined); `app.benchmark.runner.run_preset(name, config) -> BenchmarkRun`; `app.remediation.analyze.recommend(config, compromise_fraction, security_plane_integrity) -> list[Recommendation]`.
- Produces: `AuditCandidate` dataclass, `audit_remediation_candidates() -> list[AuditCandidate]`, `strongest_candidate(candidates: list[AuditCandidate]) -> AuditCandidate`, `build_audit_report(candidates, strongest) -> dict`, `render_audit_markdown(report) -> str` — consumed by `scripts/run_benchmark_audit.py`, which writes `backend/.artifacts/benchmark/audit.json` and `audit.md`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_benchmark_audit.py
from app.benchmark.audit import (
    audit_remediation_candidates,
    build_audit_report,
    render_audit_markdown,
    strongest_candidate,
)


def test_audit_finds_at_least_the_three_known_spi_candidates():
    # sentinel_compromise_attack, combined_byzantine_multi_vector, and
    # adaptive_plus_byzantine are already known (backend/.artifacts/
    # benchmark/results.json) to have security_plane_integrity < 1.0, so
    # recommend() must fire a sentinel_count recommendation for each.
    candidates = audit_remediation_candidates()
    names = {c.name for c in candidates}
    assert "sentinel_compromise_attack" in names
    assert "combined_byzantine_multi_vector" in names
    assert "adaptive_plus_byzantine" in names


def test_audit_finds_the_no_defense_candidate():
    # propagation_no_defense has compromise_fraction=1.0 and
    # defense_enabled=False, so recommend() must fire an "enable defense"
    # recommendation for it too.
    candidates = audit_remediation_candidates()
    names = {c.name for c in candidates}
    assert "propagation_no_defense" in names


def test_every_candidate_actually_improves_after_remediation():
    candidates = audit_remediation_candidates()
    assert candidates
    for c in candidates:
        assert c.after.metrics["retained_utility"] >= c.before.metrics["retained_utility"]


def test_strongest_candidate_has_the_largest_retained_utility_delta():
    candidates = audit_remediation_candidates()
    strongest = strongest_candidate(candidates)
    deltas = [c.after.metrics["retained_utility"] - c.before.metrics["retained_utility"] for c in candidates]
    assert (
        strongest.after.metrics["retained_utility"] - strongest.before.metrics["retained_utility"]
        == max(deltas)
    )


def test_build_and_render_audit_report_is_json_and_markdown_safe():
    candidates = audit_remediation_candidates()
    strongest = strongest_candidate(candidates)
    report = build_audit_report(candidates, strongest)
    assert report["strongest"]["name"] == strongest.name
    assert len(report["candidates"]) == len(candidates)
    markdown = render_audit_markdown(report)
    assert strongest.name in markdown
    assert "|" in markdown  # a markdown table was rendered
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_benchmark_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.benchmark.audit'`

- [ ] **Step 3: Implement `app/benchmark/audit.py`**

```python
"""Priority 2 of this session's brief: audits every attack-scenario and
defense-variant preset already defined in app/benchmark/matrix.py for a
remediation opportunity, re-tests each one exactly like the fixed
REMEDIATION_CASE already does in run_benchmark.py, and surfaces the single
candidate with the largest measured retained_utility improvement -- the
strongest real remediation result across the full matrix, not just the one
hand-picked case. Reuses run_preset and recommend() verbatim; no new
simulation or remediation logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.benchmark.matrix import ATTACK_SCENARIOS, DEFENSE_BASE_ATTACK, DEFENSE_VARIANTS
from app.benchmark.runner import BenchmarkRun, run_preset
from app.remediation.analyze import Recommendation, recommend
from app.schemas.experiment import ExperimentConfig


@dataclass
class AuditCandidate:
    name: str
    recommendation: Recommendation
    before: BenchmarkRun
    after: BenchmarkRun

    @property
    def retained_utility_delta(self) -> float:
        return self.after.metrics["retained_utility"] - self.before.metrics["retained_utility"]

    @property
    def security_plane_integrity_delta(self) -> float:
        return (
            self.after.metrics["security_plane_integrity"]
            - self.before.metrics["security_plane_integrity"]
        )

    @property
    def compromise_fraction_delta(self) -> float:
        return self.after.metrics["compromise_fraction"] - self.before.metrics["compromise_fraction"]


def _candidate_configs() -> dict[str, ExperimentConfig]:
    """The 14 attack scenarios plus the 7 defense-posture variants of the
    fixed defense-comparison attack -- every config app/benchmark/matrix.py
    already defines, excluding the 2,500-agent scale run (its own presence
    in ATTACK_SCENARIOS as a BenchmarkConfig, not ExperimentConfig, is
    intentionally excluded here: recommend() takes an ExperimentConfig, and
    the scale run already measures compromise_fraction=0.0/spi=1.0 -- no
    recommendation would fire for it regardless)."""
    configs: dict[str, ExperimentConfig] = {
        name: config
        for name, config in ATTACK_SCENARIOS.items()
        if isinstance(config, ExperimentConfig)
    }
    for name, overrides in DEFENSE_VARIANTS.items():
        configs[f"defense_variant_{name}"] = DEFENSE_BASE_ATTACK.model_copy(update=overrides)
    return configs


def audit_remediation_candidates() -> list[AuditCandidate]:
    candidates: list[AuditCandidate] = []
    for name, config in _candidate_configs().items():
        before = run_preset(name, config)
        recs = recommend(
            config,
            compromise_fraction=before.metrics["compromise_fraction"],
            security_plane_integrity=before.metrics["security_plane_integrity"],
        )
        if not recs:
            continue
        after = run_preset(f"{name}_remediated", config.model_copy(update=recs[0].config_diff))
        candidates.append(AuditCandidate(name=name, recommendation=recs[0], before=before, after=after))
    return candidates


def strongest_candidate(candidates: list[AuditCandidate]) -> AuditCandidate:
    return max(candidates, key=lambda c: c.retained_utility_delta)


def _candidate_summary(c: AuditCandidate) -> dict[str, Any]:
    return {
        "name": c.name,
        "recommendation": c.recommendation.description,
        "config_diff": c.recommendation.config_diff,
        "retained_utility_before": c.before.metrics["retained_utility"],
        "retained_utility_after": c.after.metrics["retained_utility"],
        "retained_utility_delta": c.retained_utility_delta,
        "security_plane_integrity_before": c.before.metrics["security_plane_integrity"],
        "security_plane_integrity_after": c.after.metrics["security_plane_integrity"],
        "compromise_fraction_before": c.before.metrics["compromise_fraction"],
        "compromise_fraction_after": c.after.metrics["compromise_fraction"],
    }


def build_audit_report(candidates: list[AuditCandidate], strongest: AuditCandidate) -> dict[str, Any]:
    return {
        "candidates": [_candidate_summary(c) for c in candidates],
        "strongest": _candidate_summary(strongest),
    }


def render_audit_markdown(report: dict[str, Any]) -> str:
    columns = [
        "name",
        "recommendation",
        "retained_utility_before",
        "retained_utility_after",
        "retained_utility_delta",
        "security_plane_integrity_before",
        "security_plane_integrity_after",
    ]
    lines = ["# AgentShield Remediation Audit", ""]
    lines.append(
        f"{len(report['candidates'])} of the benchmark matrix's presets triggered a "
        "remediation recommendation; ranked by measured retained_utility improvement."
    )
    lines.append("")
    lines.append("## Strongest result")
    strongest = report["strongest"]
    lines.append(f"**{strongest['name']}**: {strongest['recommendation']}")
    lines.append(
        f"retained_utility {strongest['retained_utility_before']:.4f} -> "
        f"{strongest['retained_utility_after']:.4f} "
        f"(+{strongest['retained_utility_delta']:.4f})"
    )
    lines.append("")
    lines.append("## All candidates")
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    lines.append(header)
    lines.append(separator)
    ranked = sorted(report["candidates"], key=lambda c: -c["retained_utility_delta"])
    for row in ranked:
        lines.append("| " + " | ".join(str(row[c]) for c in columns) + " |")
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_benchmark_audit.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Write the artifact-writing script**

```python
#!/usr/bin/env python3
# backend/scripts/run_benchmark_audit.py
"""Priority 2: audits every attack-scenario/defense-variant preset for a
remediation opportunity and writes the ranked results to
backend/.artifacts/benchmark/{audit.json,audit.md}. Separate from
run_benchmark.py's single fixed REMEDIATION_CASE -- this sweeps the whole
matrix to surface the single strongest real remediation result.
"""

import json
from pathlib import Path

from app.benchmark.audit import (
    audit_remediation_candidates,
    build_audit_report,
    render_audit_markdown,
    strongest_candidate,
)

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / ".artifacts" / "benchmark"


def main() -> int:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    candidates = audit_remediation_candidates()
    if not candidates:
        print("no remediation candidates found in the benchmark matrix")
        return 1
    strongest = strongest_candidate(candidates)
    report = build_audit_report(candidates, strongest)

    (ARTIFACTS_DIR / "audit.json").write_text(json.dumps(report, indent=2))
    (ARTIFACTS_DIR / "audit.md").write_text(render_audit_markdown(report))

    print(f"Strongest result: {strongest.name} -- {strongest.recommendation.description}")
    print(
        f"retained_utility {strongest.before.metrics['retained_utility']:.4f} -> "
        f"{strongest.after.metrics['retained_utility']:.4f}"
    )
    print(f"Wrote {ARTIFACTS_DIR / 'audit.json'} and {ARTIFACTS_DIR / 'audit.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Add the Makefile target**

In `/home/danda/projects/agentNet/Makefile`, add after the existing `benchmark:` target:

```makefile
# Priority 2 of this session's brief: sweeps every attack-scenario/defense-
# variant preset for a remediation opportunity and ranks the results by
# measured retained_utility improvement. Writes
# backend/.artifacts/benchmark/{audit.json,audit.md}.
benchmark-audit:
	cd backend && .venv/bin/python scripts/run_benchmark_audit.py
```

Add `benchmark-audit` to the `.PHONY` line at the top of the file.

- [ ] **Step 7: Run it for real and inspect the output**

Run: `cd backend && .venv/bin/python scripts/run_benchmark_audit.py`
Expected: prints the strongest result and writes both artifact files; read `backend/.artifacts/benchmark/audit.md` afterward to confirm the numbers are sane (a positive `retained_utility_delta`, a legible Markdown table).

- [ ] **Step 8: Full backend regression**

Run: `cd backend && POSTGRES_DB=agentnet_test .venv/bin/pytest && .venv/bin/ruff check .`
Expected: all pass

- [ ] **Step 9: Commit**

```bash
git add backend/app/benchmark/audit.py backend/scripts/run_benchmark_audit.py backend/tests/test_benchmark_audit.py backend/.artifacts/benchmark/audit.json backend/.artifacts/benchmark/audit.md Makefile
git commit -m "feat(benchmark): audit the full scenario/defense matrix for the strongest remediation result"
```

---

### Task 7: Harden `agentshield_test.py` for CI (priority 3)

**Files:**
- Modify: `backend/scripts/agentshield_test.py`
- Modify: `backend/app/benchmark/cli.py`
- Test: `backend/tests/test_benchmark_cli.py` (create if it doesn't already exist — check first: `ls backend/tests/test_benchmark_cli.py` — if it exists, extend it instead)

**Interfaces:**
- Consumes: existing `app.benchmark.cli.evaluate() -> list[Finding]` (unchanged pass/fail logic — this task only changes how findings are reported, not what's checked, per the global constraint of not adding speculative complexity).
- Produces: `Finding` gains a `duration_s: float` field; `evaluate()` returns findings with that field populated; `agentshield_test.py` gains a `--json` flag producing a single-line machine-readable summary object; text mode gains a total-duration/pass-count summary line.

- [ ] **Step 1: Check for an existing CLI test file**

Run: `ls backend/tests/test_benchmark_cli.py 2>&1`. If it exists, read it fully before writing new tests so they extend rather than duplicate it.

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_benchmark_cli.py (new, or appended if the file already exists)
import json
import subprocess
import sys

from app.benchmark.cli import evaluate


def test_evaluate_findings_include_a_nonnegative_duration():
    findings = evaluate()
    assert findings
    for finding in findings:
        assert finding.duration_s >= 0.0


def test_cli_json_mode_prints_one_valid_json_object_with_all_findings():
    result = subprocess.run(
        [sys.executable, "scripts/agentshield_test.py", "--json"],
        capture_output=True,
        text=True,
        cwd=".",
    )
    payload = json.loads(result.stdout)
    assert "ok" in payload
    assert isinstance(payload["findings"], list)
    assert len(payload["findings"]) >= 2
    for finding in payload["findings"]:
        assert {"name", "passed", "detail", "duration_s"} <= finding.keys()
    assert result.returncode == (0 if payload["ok"] else 1)


def test_cli_text_mode_prints_a_summary_line():
    result = subprocess.run(
        [sys.executable, "scripts/agentshield_test.py"],
        capture_output=True,
        text=True,
        cwd=".",
    )
    assert "PASS" in result.stdout or "FAIL" in result.stdout
    assert "/" in result.stdout.splitlines()[-1]  # e.g. "2/2 findings passed in 1.2s"
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_benchmark_cli.py -v`
Expected: FAIL — `Finding` has no `duration_s` attribute yet, `--json` is an unrecognized argument.

- [ ] **Step 4: Implement**

In `backend/app/benchmark/cli.py`, add timing:

```python
from __future__ import annotations

import time
from dataclasses import dataclass

from app.benchmark.golden_demo import run_golden_demo
from app.benchmark.matrix import DEFENSE_BASE_ATTACK, DEFENSE_VARIANTS
from app.benchmark.runner import run_preset


@dataclass
class Finding:
    name: str
    passed: bool
    detail: str
    duration_s: float


def evaluate() -> list[Finding]:
    findings: list[Finding] = []

    start = time.monotonic()
    off = run_preset(
        "defense_off", DEFENSE_BASE_ATTACK.model_copy(update=DEFENSE_VARIANTS["defense_off"])
    )
    high = run_preset(
        "defense_high_sensitivity",
        DEFENSE_BASE_ATTACK.model_copy(update=DEFENSE_VARIANTS["defense_high_sensitivity"]),
    )
    passed = high.metrics["retained_utility"] >= off.metrics["retained_utility"]
    findings.append(
        Finding(
            name="high-sensitivity defense retains at least as much utility as no defense",
            passed=passed,
            detail=(
                f"defense_off retained_utility={off.metrics['retained_utility']:.2f}, "
                f"defense_high_sensitivity={high.metrics['retained_utility']:.2f}"
            ),
            duration_s=time.monotonic() - start,
        )
    )

    start = time.monotonic()
    demo = run_golden_demo()
    demo_passed = demo.rerun is not None and (
        demo.rerun.metrics["security_plane_integrity"]
        >= demo.baseline.metrics["security_plane_integrity"]
    )
    findings.append(
        Finding(
            name="golden demo remediation improves security_plane_integrity",
            passed=demo_passed,
            detail=(
                f"baseline={demo.baseline.metrics['security_plane_integrity']:.2f}, "
                f"rerun={(demo.rerun.metrics['security_plane_integrity'] if demo.rerun else None)}"
            ),
            duration_s=time.monotonic() - start,
        )
    )

    return findings
```

In `backend/scripts/agentshield_test.py`:

```python
#!/usr/bin/env python3
"""agentshield test: CI-friendly pass/fail gate over a fast subset of the
benchmark suite + golden demo. Exit 0 if every finding passes, else 1.
Pass --json for a single machine-readable line (CI log parsers, dashboards)
instead of the default human-readable PASS/FAIL lines."""

import argparse
import json
import time
from dataclasses import asdict

from app.benchmark.cli import evaluate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    args = parser.parse_args()

    start = time.monotonic()
    findings = evaluate()
    total_duration = time.monotonic() - start
    ok = all(f.passed for f in findings)
    passed_count = sum(1 for f in findings if f.passed)

    if args.json:
        payload = {
            "ok": ok,
            "findings": [asdict(f) for f in findings],
            "duration_s": round(total_duration, 4),
        }
        print(json.dumps(payload))
    else:
        for finding in findings:
            status = "PASS" if finding.passed else "FAIL"
            print(f"[{status}] {finding.name}: {finding.detail} ({finding.duration_s:.2f}s)")
        print(f"{passed_count}/{len(findings)} findings passed in {total_duration:.2f}s")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_benchmark_cli.py -v && .venv/bin/python scripts/agentshield_test.py && .venv/bin/python scripts/agentshield_test.py --json`
Expected: tests pass; text mode shows two `[PASS]` lines plus a summary line; `--json` mode prints one parseable JSON line; both exit 0.

- [ ] **Step 6: Full backend regression**

Run: `cd backend && POSTGRES_DB=agentnet_test .venv/bin/pytest && .venv/bin/ruff check .`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add backend/app/benchmark/cli.py backend/scripts/agentshield_test.py backend/tests/test_benchmark_cli.py
git commit -m "feat(cli): add --json output and per-finding timing to agentshield test"
```

---

### Task 8: Strengthen LangGraph import regression coverage (priority 4)

**Files:**
- Modify: `backend/tests/test_external_topology_importer.py`
- Modify: `backend/tests/test_external_import_demo.py`

**Interfaces:**
- Consumes: existing `load_topology_json`, `ExternalTopology` (`app/importers/external_topology.py`); the committed `backend/.artifacts/external_import/result.json` numbers as the golden-file baseline.
- Produces: no new production code — only new test cases pinning current real behavior, so a future change that silently breaks the importer or its measured numbers is caught.

- [ ] **Step 1: Add golden-file regression test to `test_external_import_demo.py`**

```python
def test_imported_topology_matches_the_committed_result_artifact():
    """Pins the real measured numbers in backend/.artifacts/external_import/
    result.json -- regenerate that artifact (`make import-demo`) and update
    this test together if a deliberate engine/scenario change legitimately
    moves these numbers; a silent drift here means the importer or the
    scenario composition broke, not that the pin is stale."""
    topology = load_topology_json(TOPOLOGY_PATH)
    config = ExperimentConfig(
        seed=42,
        node_count=25,
        sentinel_count=1,
        sentinel_compromise_rate=0.3,
        active_scenarios=["propagation", "sentinel_compromise"],
        defense_enabled=True,
    )
    world, _ = build_world_from_agents(
        topology.agents, {tuple(e) for e in topology.edges}, config
    )
    while not is_finished(world, config):
        world, _ = advance(world, config)
    graph = build_security_graph(world, config)

    assert compromise_fraction(world) == 1.0
    assert security_plane_integrity(graph) == 0.8
```

Add the needed imports at the top of the file if not already present: `from app.metrics.compute import compromise_fraction` is already imported per this file's existing content — no new import needed for this test beyond what's already there.

- [ ] **Step 2: Add error-path tests to `test_external_topology_importer.py`**

```python
def test_load_topology_json_raises_for_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_topology_json(tmp_path / "does_not_exist.json")


def test_load_topology_json_raises_for_malformed_json(tmp_path: Path):
    path = tmp_path / "malformed.json"
    path.write_text("{not valid json")
    with pytest.raises(json.JSONDecodeError):
        load_topology_json(path)


def test_load_topology_json_raises_for_missing_required_field(tmp_path: Path):
    path = tmp_path / "missing_agents.json"
    path.write_text(json.dumps({"edges": []}))
    with pytest.raises(ValidationError):
        load_topology_json(path)


def test_load_topology_json_raises_for_edge_referencing_unknown_agent_shape(tmp_path: Path):
    # edges must be pairs -- a malformed triple should fail validation, not
    # silently truncate.
    path = tmp_path / "bad_edge_shape.json"
    path.write_text(json.dumps({"agents": ["a", "b"], "edges": [["a", "b", "c"]]}))
    with pytest.raises(ValidationError):
        load_topology_json(path)
```

Add the needed imports at the top of `test_external_topology_importer.py`: `import json` and `from pydantic import ValidationError` (check the existing import block first and only add what's missing — `pytest` and `Path` are already imported per the file content already read).

- [ ] **Step 3: Run to verify all pass**

Run: `cd backend && .venv/bin/pytest tests/test_external_topology_importer.py tests/test_external_import_demo.py -v`
Expected: PASS (all old and new tests)

- [ ] **Step 4: Full backend regression**

Run: `cd backend && POSTGRES_DB=agentnet_test .venv/bin/pytest && .venv/bin/ruff check .`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_external_topology_importer.py backend/tests/test_external_import_demo.py
git commit -m "test(import): pin external-import measured numbers and cover malformed topology.json"
```

---

### Task 9: Golden demo key-beats summary (priority 5)

**Files:**
- Modify: `backend/app/benchmark/golden_demo.py`
- Modify: `backend/scripts/run_golden_demo.py`
- Modify: `backend/tests/test_golden_demo.py`

**Interfaces:**
- Consumes: existing `GoldenDemoResult.narrative: list[str]`.
- Produces: `summarize_golden_demo_narrative(narrative: list[str]) -> list[str]` (pure, tested) — a curated subset of the full narrative with the noisy repeated "compromise propagated to X" lines collapsed, consumed by `run_golden_demo.py` to print/write a "Key beats" section above the full chronological log.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_golden_demo.py`:

```python
from app.benchmark.golden_demo import run_golden_demo, summarize_golden_demo_narrative


def test_summarize_golden_demo_narrative_collapses_repeated_propagation_lines():
    narrative = [
        "tick 1: seeded initial compromise at agent-000",
        "tick 2: compromise propagated to agent-001",
        "tick 3: compromise propagated to agent-002",
        "tick 4: compromise propagated to agent-003",
        "tick 5: agent-004 quarantined by initial defense",
    ]
    summary = summarize_golden_demo_narrative(narrative)
    propagated_lines = [line for line in summary if "compromise propagated to" in line]
    assert len(propagated_lines) <= 1
    assert "seeded initial compromise at agent-000" in "\n".join(summary)
    assert "quarantined by initial defense" in "\n".join(summary)


def test_summarize_golden_demo_narrative_preserves_order_and_all_required_beats():
    result = run_golden_demo()
    summary = summarize_golden_demo_narrative(result.narrative)
    required_substrings = [
        "prompt injection",
        "quarantined",
        "adaptive attacker",
        "sentinel",
        "false threat signature",
        "security_plane_integrity",
        "remediation recommended",
        "re-ran",
    ]
    joined = "\n".join(summary)
    for substring in required_substrings:
        assert substring in joined, f"missing beat evidence in summary: {substring!r}"
    # order-preserving: summary is a subsequence of the full narrative
    it = iter(result.narrative)
    assert all(line in it for line in summary)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_golden_demo.py -v`
Expected: FAIL with `ImportError: cannot import name 'summarize_golden_demo_narrative'`

- [ ] **Step 3: Implement in `golden_demo.py`**

Add after `_narrate`:

```python
def summarize_golden_demo_narrative(narrative: list[str]) -> list[str]:
    """Curated subset of the full narrative for the demo's headline output:
    keeps every distinct beat line but collapses the many repeated
    "compromise propagated to X" lines (one per newly-compromised agent,
    often 20-60+ of them) down to the first occurrence, so the story's ten
    beats read as a short list instead of being buried in bulk propagation
    noise. The full, uncollapsed narrative remains available via
    GoldenDemoResult.narrative for anyone who wants the tick-by-tick log."""
    summary: list[str] = []
    seen_propagation_line = False
    for line in narrative:
        if "compromise propagated to" in line:
            if seen_propagation_line:
                continue
            seen_propagation_line = True
        summary.append(line)
    return summary
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_golden_demo.py -v`
Expected: PASS

- [ ] **Step 5: Use it in the script**

In `backend/scripts/run_golden_demo.py`, change the import and report-writing:

```python
from app.benchmark.golden_demo import run_golden_demo, summarize_golden_demo_narrative
```

```python
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    result = run_golden_demo(model_provider=args.model_provider)
    key_beats = summarize_golden_demo_narrative(result.narrative)

    lines = ["# AgentShield Golden Demo", "", "## Key beats", ""]
    lines.extend(key_beats)
    lines.extend(["", "## Full narrative", ""])
    lines.extend(result.narrative)
    (ARTIFACTS_DIR / "report.md").write_text("\n".join(lines))

    summary = {
        "baseline_metrics": result.baseline.metrics,
        "recommendation": result.recommendation.description if result.recommendation else None,
        "rerun_metrics": result.rerun.metrics if result.rerun else None,
    }
    (ARTIFACTS_DIR / "result.json").write_text(json.dumps(summary, indent=2))

    print("\n".join(key_beats))
    print(f"\nWrote {ARTIFACTS_DIR / 'report.md'} and {ARTIFACTS_DIR / 'result.json'}")
    return 0
```

- [ ] **Step 6: Run for real and inspect**

Run: `cd backend && .venv/bin/python scripts/run_golden_demo.py`
Expected: stdout shows only the curated key beats (roughly a dozen lines, not 60+); `backend/.artifacts/golden_demo/report.md` has a short "Key beats" section followed by the full narrative.

- [ ] **Step 7: Full backend regression**

Run: `cd backend && POSTGRES_DB=agentnet_test .venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/python scripts/agentshield_test.py`
Expected: all pass (agentshield_test.py calls `run_golden_demo()` directly, unaffected by the script-level summary change)

- [ ] **Step 8: Commit**

```bash
git add backend/app/benchmark/golden_demo.py backend/scripts/run_golden_demo.py backend/tests/test_golden_demo.py backend/.artifacts/golden_demo/report.md backend/.artifacts/golden_demo/result.json
git commit -m "feat(golden-demo): surface a curated key-beats summary above the full narrative"
```

---

### Task 10: Reconcile docs and reaffirm the typed-node-rendering decision (priorities 6 & 7)

**Files:**
- Modify: `docs/PLAN.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: the real artifacts/numbers produced by Tasks 1-9 (`backend/.artifacts/benchmark/{results.json,report.md,audit.json,audit.md}`, `backend/.artifacts/golden_demo/{report.md,result.json}`, the new `/replay/...` routes, `agentshield_test.py --json` output).
- Produces: an updated §9 "Explicitly remaining" list, an updated §10 "Next recommended milestone" (or a new §11 documenting this session), and a README section documenting the new `make benchmark-audit` target and `agentshield_test.py --json` flag — no code changes in this task.

- [ ] **Step 1: Update `docs/PLAN.md` §9's "Explicitly remaining" list**

Remove item 1's implication that history/replay is unaddressed by adding a note that item 1 (typed-node rendering) is the *only* remaining item from that list this session did not touch, and that the "Next recommended milestone" section (§10) has been superseded — read the current §9/§10 text first (already read this session — lines 467-487 and 595-603) and edit precisely:

- In §10's "Next recommended milestone" paragraph (lines 595-603), replace the sentence describing the history/replay gap as still-open with a note that it is now closed, pointing at the new `/replay/...` routes and this session's date, and update the remaining two items (browser pass on `NetworkGraph.tsx`, real Qwen/vLLM run) to state they are still the only two open items.

- [ ] **Step 2: Add a new `## 11. Continuation: history/replay parity, remediation audit, CI hardening` section to `docs/PLAN.md`**

Document, with real numbers pulled from the artifacts generated in Tasks 1-9 (do not fabricate — copy from the actual files on disk after running this plan):
- The `/replay/graph`, `/replay/analysis/*`, `/replay/metrics`, `/replay/remediation` routes and the `app/engine/replay.py` mechanism, including the real-provider replay limitation.
- The comparison view's rich-metrics parity change.
- The audit script's actual strongest result (name, recommendation, before/after retained_utility) copied from `backend/.artifacts/benchmark/audit.md`.
- The `agentshield_test.py --json` addition.
- The external-import golden-file pin and error-path tests added.
- The golden demo's key-beats summary.
- Priority 7 (typed-node rendering): state plainly that this session again had no browser/screenshot tool available (confirmed via `ToolSearch` at the start of this session) and again deliberately left `NetworkGraph.tsx` untouched, consistent with every prior session's documented decision.

- [ ] **Step 3: Update README.md**

In the "Canonical benchmark suite, golden demo, and external integration" section (around line 236), add `run_benchmark_audit.py` / `make benchmark-audit` to the listed commands, with one sentence on what it does and its real strongest-result numbers. In whatever section documents `agentshield_test.py` (around line 261), add a sentence documenting the `--json` flag.

- [ ] **Step 4: Verify the docs build/render sanely and nothing else regressed**

Run the full verification sweep one final time:

```bash
cd backend && POSTGRES_DB=agentnet_test .venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/python scripts/verify_determinism.py
cd ../frontend && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
cd ../backend && .venv/bin/python scripts/run_benchmark.py && .venv/bin/python scripts/run_benchmark_audit.py && .venv/bin/python scripts/run_golden_demo.py && .venv/bin/python scripts/run_external_import_demo.py && .venv/bin/python scripts/agentshield_test.py && .venv/bin/python scripts/agentshield_test.py --json
```

Expected: everything passes; every artifact file under `backend/.artifacts/` is freshly regenerated and matches what was written into `docs/PLAN.md`/`README.md` in Steps 1-3. If schema drift shows up (new `/replay/...` routes not yet in `schema.d.ts`), also run: `cd backend && POSTGRES_DB=agentnet_test .venv/bin/uvicorn app.main:app &`, then `cd frontend && npx openapi-typescript http://localhost:8000/openapi.json -o src/lib/api/schema.d.ts && git diff --exit-code src/lib/api/schema.d.ts` (should be empty if Task 3 already regenerated it correctly), then stop the background uvicorn.

- [ ] **Step 5: Commit**

```bash
git add docs/PLAN.md README.md
git commit -m "docs: reconcile PLAN/README with history/replay parity, audit, and CLI hardening"
```

---

## Final delivery steps (after all 10 tasks are committed)

- [ ] Run the entire verification sweep from Task 10 Step 4 one more time from a clean checkout state (`git status` shows nothing uncommitted) to confirm the full commit sequence is self-consistent.
- [ ] `git push` to `origin main` (confirm with the user first per this session's operating instructions on actions visible to others).
- [ ] Check CI: `gh run list --limit 3` and `gh run watch <run-id>` (or poll) until the push's run completes; if it fails, fix forward with a new commit rather than force-pushing.
- [ ] Report to the user: exact pass/fail counts for backend pytest and frontend vitest, the exact strongest-remediation-audit result (name + before/after numbers), the exact `agentshield_test.py --json` output, and a one-line note that real Qwen/vLLM validation remains manual and unexercised this session (no reachable GPU endpoint), with the exact command from README to run it when one is available.
