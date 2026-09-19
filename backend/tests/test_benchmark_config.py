import pytest
from pydantic import ValidationError

from app.benchmark.config import BenchmarkConfig
from app.schemas.experiment import ExperimentConfig


def test_benchmark_config_allows_2500_nodes():
    config = BenchmarkConfig(seed=1, node_count=2500)
    assert config.node_count == 2500


def test_live_experiment_config_still_rejects_2500_nodes():
    with pytest.raises(ValidationError):
        ExperimentConfig(seed=1, node_count=2500)


def test_benchmark_config_is_otherwise_identical_to_experiment_config():
    bench = BenchmarkConfig(seed=1, node_count=60)
    live = ExperimentConfig(seed=1, node_count=60)
    assert bench.model_dump(exclude={"node_count"}) == live.model_dump(exclude={"node_count"})
