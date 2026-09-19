import uuid

from app.orchestrator.registry import ExperimentRegistry
from app.orchestrator.runner import ExperimentRunner
from app.schemas.experiment import ExperimentConfig


def _make_runner() -> ExperimentRunner:
    return ExperimentRunner(ExperimentConfig(seed=1, node_count=25, max_ticks=5))


def test_add_then_get_returns_same_runner():
    registry = ExperimentRegistry()
    runner = _make_runner()
    registry.add(runner)
    assert registry.get(runner.experiment_id) is runner


def test_get_missing_id_returns_none():
    registry = ExperimentRegistry()
    assert registry.get(uuid.uuid4()) is None


def test_remove_then_get_returns_none():
    registry = ExperimentRegistry()
    runner = _make_runner()
    registry.add(runner)
    registry.remove(runner.experiment_id)
    assert registry.get(runner.experiment_id) is None


def test_remove_of_absent_id_is_noop():
    registry = ExperimentRegistry()
    registry.remove(uuid.uuid4())
