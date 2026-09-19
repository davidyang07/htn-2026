import asyncio

from app.orchestrator.runner import ExperimentRunner
from app.schemas.experiment import ExperimentConfig


def _make_runner(**overrides) -> ExperimentRunner:
    config = ExperimentConfig(
        seed=42, node_count=25, max_ticks=5, active_scenarios=["adaptive_attacker"], **overrides
    )
    runner = ExperimentRunner(config)
    runner.tick_interval = 0
    return runner


async def _drive_to_finished(runner: ExperimentRunner) -> None:
    await runner.publish_initial()
    await runner._run_loop()


def test_adaptive_attacker_drives_a_full_experiment_through_the_runner():
    runner = _make_runner()
    asyncio.run(_drive_to_finished(runner))

    assert runner.status == "finished"
    assert runner.state.tick > 0


def test_adaptive_attacker_is_deterministic_through_the_runner():
    runner_a = _make_runner()
    runner_b = _make_runner()

    asyncio.run(_drive_to_finished(runner_a))
    asyncio.run(_drive_to_finished(runner_b))

    assert runner_a.state == runner_b.state
