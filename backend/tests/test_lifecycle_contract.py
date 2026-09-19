import asyncio

import pytest

from app.orchestrator.runner import ExperimentRunner, InvalidTransitionError
from app.schemas.experiment import ExperimentConfig


def _make_runner(**overrides) -> ExperimentRunner:
    config = ExperimentConfig(seed=42, node_count=25, max_ticks=5, **overrides)
    runner = ExperimentRunner(config)
    runner.tick_interval = 0
    return runner


async def _drive_to_finished(runner: ExperimentRunner) -> None:
    await runner.publish_initial()
    await runner._run_loop()


def test_pause_from_running_transitions_to_paused():
    runner = _make_runner()
    runner.pause()
    assert runner.status == "paused"


def test_pause_while_already_paused_is_idempotent_noop():
    runner = _make_runner()
    runner.pause()
    runner.pause()
    assert runner.status == "paused"


def test_pause_on_finished_raises_invalid_transition():
    runner = _make_runner()
    asyncio.run(_drive_to_finished(runner))
    assert runner.status == "finished"
    with pytest.raises(InvalidTransitionError):
        runner.pause()


def test_pause_on_stopped_raises_invalid_transition():
    runner = _make_runner()
    asyncio.run(runner.stop())
    assert runner.status == "stopped"
    with pytest.raises(InvalidTransitionError):
        runner.pause()


def test_resume_from_paused_transitions_to_running():
    runner = _make_runner()
    runner.pause()
    runner.resume()
    assert runner.status == "running"


def test_resume_while_already_running_is_idempotent_noop():
    runner = _make_runner()
    runner.resume()
    assert runner.status == "running"


def test_resume_on_finished_raises_invalid_transition():
    runner = _make_runner()
    asyncio.run(_drive_to_finished(runner))
    with pytest.raises(InvalidTransitionError):
        runner.resume()


def test_resume_on_stopped_raises_invalid_transition():
    runner = _make_runner()
    asyncio.run(runner.stop())
    with pytest.raises(InvalidTransitionError):
        runner.resume()


def test_set_speed_valid_while_running():
    runner = _make_runner()
    runner.set_speed(2.0)
    assert runner._speed == 2.0


def test_set_speed_valid_while_paused():
    runner = _make_runner()
    runner.pause()
    runner.set_speed(4.0)
    assert runner._speed == 4.0


def test_set_speed_clamps_above_max():
    runner = _make_runner()
    runner.set_speed(100.0)
    assert runner._speed == 8.0


def test_set_speed_clamps_below_min():
    runner = _make_runner()
    runner.set_speed(0.001)
    assert runner._speed == 0.25


def test_set_speed_on_finished_raises_invalid_transition():
    runner = _make_runner()
    asyncio.run(_drive_to_finished(runner))
    with pytest.raises(InvalidTransitionError):
        runner.set_speed(2.0)


def test_set_speed_on_stopped_raises_invalid_transition():
    runner = _make_runner()
    asyncio.run(runner.stop())
    with pytest.raises(InvalidTransitionError):
        runner.set_speed(2.0)


def test_stop_from_running_transitions_to_stopped():
    runner = _make_runner()
    asyncio.run(runner.stop())
    assert runner.status == "stopped"


def test_stop_from_paused_transitions_to_stopped():
    runner = _make_runner()
    runner.pause()
    asyncio.run(runner.stop())
    assert runner.status == "stopped"


def test_stop_on_finished_is_idempotent_noop():
    runner = _make_runner()
    asyncio.run(_drive_to_finished(runner))
    asyncio.run(runner.stop())
    assert runner.status == "finished"


def test_stop_on_stopped_is_idempotent_noop():
    runner = _make_runner()
    asyncio.run(runner.stop())
    asyncio.run(runner.stop())
    assert runner.status == "stopped"
