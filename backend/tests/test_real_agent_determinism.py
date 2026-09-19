"""Tier 2 determinism (docs/PHASE_2_PLAN.md §9): a hybrid experiment
(real_agent_count > 0) driven through the real async ExperimentRunner with a
MockProvider-backed gateway is fully deterministic -- same as Tier 1's
verify_determinism.py proves for the synthetic baseline, but for the new
async real-agent code path, which run_full()'s purely-synchronous harness
cannot exercise."""

import asyncio
from uuid import uuid4

from app.engine.simulate import run_full
from app.events.emitter import EventEmitter
from app.gateway.gateway import ModelGateway
from app.gateway.mock_provider import MockProvider
from app.orchestrator.runner import ExperimentRunner
from app.schemas.experiment import ExperimentConfig


def _project(e) -> tuple:
    return (
        e.seq,
        e.sim_tick,
        e.event_type,
        e.agent_id,
        e.source_agent_id,
        e.target_agent_id,
        e.metadata,
    )


def _hybrid_config(seed: int) -> ExperimentConfig:
    return ExperimentConfig(seed=seed, node_count=60, real_agent_count=8, max_ticks=20)


def _drive(config: ExperimentConfig) -> list:
    async def run() -> list:
        gateway = ModelGateway(
            MockProvider(),
            timeout_s=5.0,
            max_retries=1,
            max_concurrency=8,
            max_requests_per_experiment=1000,
        )
        runner = ExperimentRunner(config, gateway=gateway)
        runner.tick_interval = 0
        await runner.publish_initial()
        await runner._run_loop()
        return [_project(e) for e in runner.bus.since(-1)]

    return asyncio.run(run())


def test_hybrid_run_is_deterministic_at_same_seed():
    config = _hybrid_config(42)
    run1 = _drive(config)
    run2 = _drive(config)
    assert run1 == run2

    # Not a vacuous pass -- assert the hybrid path actually exercised the
    # real-agent code (MODEL_REQUESTED present), not just an empty overlap.
    event_types = {e[2].value for e in run1}
    assert "MODEL_REQUESTED" in event_types
    assert "MODEL_RESPONDED" in event_types


def test_hybrid_run_differs_at_different_seed():
    run_a = _drive(_hybrid_config(42))
    run_b = _drive(_hybrid_config(43))
    assert run_a != run_b


def test_real_agent_count_zero_matches_pure_synthetic_baseline():
    """The other half of the additivity claim (docs/PHASE_2_PLAN.md §9 tier
    1): driving the runner with real_agent_count=0 (no gateway needed at
    all, matching production wiring where build_gateway() returns None)
    must be identical to the same run with a gateway constructed but never
    invoked, proving real_agent_step's early return is truly a no-op."""
    config = ExperimentConfig(seed=42, node_count=60, real_agent_count=0, max_ticks=200)

    async def run_with_gateway() -> list:
        gateway = ModelGateway(
            MockProvider(), timeout_s=5.0, max_retries=1, max_concurrency=8,
            max_requests_per_experiment=1000,
        )
        runner = ExperimentRunner(config, gateway=gateway)
        runner.tick_interval = 0
        await runner.publish_initial()
        await runner._run_loop()
        return [_project(e) for e in runner.bus.since(-1)]

    with_gateway = asyncio.run(run_with_gateway())
    baseline = [
        _project(e) for e in EventEmitter(experiment_id=uuid4()).emit(run_full(config))
    ]
    assert with_gateway == baseline
