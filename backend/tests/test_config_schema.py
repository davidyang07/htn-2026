import pytest
from pydantic import ValidationError

from app.engine.state import SecurityState
from app.schemas.experiment import ExperimentConfig, NodeView, SpeedRequest


def test_experiment_config_new_fields_have_m0_preserving_defaults():
    config = ExperimentConfig(seed=1)
    assert config.detector_sensitivity == 0.2
    assert config.defense_enabled is True
    assert config.initial_compromised == "highest_degree"


def test_default_active_scenarios_includes_prompt_injection():
    # docs/PLAN.md §3: real_agent_count > 0 must keep working exactly as
    # before app/scenarios/registry.py::run_async_scenarios started gating
    # by active_scenarios, so the default must include "prompt_injection".
    config = ExperimentConfig(seed=1)
    assert config.active_scenarios == ["propagation", "prompt_injection"]


def test_detector_sensitivity_accepts_explicit_value_in_bounds():
    config = ExperimentConfig(seed=1, detector_sensitivity=0.75)
    assert config.detector_sensitivity == 0.75


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_detector_sensitivity_rejects_out_of_bounds(value):
    with pytest.raises(ValidationError):
        ExperimentConfig(seed=1, detector_sensitivity=value)


def test_defense_enabled_accepts_explicit_false():
    config = ExperimentConfig(seed=1, defense_enabled=False)
    assert config.defense_enabled is False


def test_initial_compromised_accepts_random_node():
    config = ExperimentConfig(seed=1, initial_compromised="random_node")
    assert config.initial_compromised == "random_node"


def test_initial_compromised_rejects_unknown_strategy():
    with pytest.raises(ValidationError):
        ExperimentConfig(seed=1, initial_compromised="not_a_real_strategy")


def test_node_view_new_fields_are_optional_and_default_none():
    node = NodeView(id="agent-000", software_type="sw-a", security_state=SecurityState.HEALTHY)
    assert node.compromised_by is None
    assert node.tick_compromised is None


def test_node_view_new_fields_accept_explicit_values():
    node = NodeView(
        id="agent-001",
        software_type="sw-a",
        security_state=SecurityState.COMPROMISED,
        compromised_by="agent-000",
        tick_compromised=3,
    )
    assert node.compromised_by == "agent-000"
    assert node.tick_compromised == 3


def test_speed_request_accepts_in_bounds_multiplier():
    req = SpeedRequest(multiplier=2.0)
    assert req.multiplier == 2.0


@pytest.mark.parametrize("value", [0.1, 8.1])
def test_speed_request_rejects_out_of_bounds_multiplier(value):
    with pytest.raises(ValidationError):
        SpeedRequest(multiplier=value)


def test_speed_request_requires_multiplier():
    with pytest.raises(ValidationError):
        SpeedRequest()
