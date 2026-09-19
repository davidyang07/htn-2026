"""Full-experiment integration for the Byzantine/security-plane scenarios
(docs/PLAN.md §5): sentinel_compromise, attestation, and byzantine_collusion
are composable (none owns the tick increment) and run alongside propagation
through the real ExperimentRunner, exactly like
test_adaptive_attacker_runner_integration.py does for the adaptive attacker.
"""

import asyncio

from app.orchestrator.runner import ExperimentRunner
from app.schemas.experiment import ExperimentConfig


def _make_runner(**overrides) -> ExperimentRunner:
    config = ExperimentConfig(
        seed=42,
        node_count=25,
        max_ticks=10,
        sentinel_count=2,
        credential_count=2,
        active_scenarios=[
            "propagation",
            "sentinel_compromise",
            "attestation",
            "byzantine_collusion",
        ],
        sentinel_compromise_rate=0.5,
        attestation_replay_rate=0.5,
        byzantine_collusion_rate=0.5,
        **overrides,
    )
    runner = ExperimentRunner(config)
    runner.tick_interval = 0
    return runner


async def _drive_to_finished(runner: ExperimentRunner) -> None:
    await runner.publish_initial()
    await runner._run_loop()


def test_composed_byzantine_scenarios_drive_a_full_experiment_through_the_runner():
    runner = _make_runner()
    asyncio.run(_drive_to_finished(runner))

    assert runner.status == "finished"
    assert runner.state.tick > 0


def test_composed_byzantine_scenarios_are_deterministic_through_the_runner():
    runner_a = _make_runner()
    runner_b = _make_runner()

    asyncio.run(_drive_to_finished(runner_a))
    asyncio.run(_drive_to_finished(runner_b))

    assert runner_a.state == runner_b.state
