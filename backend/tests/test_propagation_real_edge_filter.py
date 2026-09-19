from typing import Literal

from app.engine.propagation import step
from app.engine.state import AgentNode, SecurityState, WorldState
from app.schemas.experiment import ExperimentConfig

AgentKind = Literal["simulated", "real"]


def _world(source_kind: AgentKind, target_kind: AgentKind) -> WorldState:
    nodes = {
        "agent-000": AgentNode(
            id="agent-000",
            software_type="sw-a",
            security_state=SecurityState.COMPROMISED,
            neighbors=("agent-001",),
            tick_compromised=0,
            agent_kind=source_kind,
            confidential_token="TOKEN-a" if source_kind == "real" else None,
        ),
        "agent-001": AgentNode(
            id="agent-001",
            software_type="sw-a",
            security_state=SecurityState.HEALTHY,
            neighbors=("agent-000",),
            agent_kind=target_kind,
            confidential_token="TOKEN-b" if target_kind == "real" else None,
        ),
    }
    edges = (("agent-000", "agent-001"),)
    return WorldState(tick=0, nodes=nodes, edges=edges)


def _config() -> ExperimentConfig:
    # p_same=1.0 so a probabilistic attempt, if made, is unambiguous.
    return ExperimentConfig(seed=1, node_count=25, p_same=1.0)


def test_real_real_edge_is_never_attempted_by_propagation_step():
    world = _world("real", "real")
    new_world, drafts = step(world, _config())

    assert drafts == []
    assert new_world.nodes["agent-001"].security_state == SecurityState.HEALTHY


def test_simulated_simulated_edge_still_attempted():
    world = _world("simulated", "simulated")
    _, drafts = step(world, _config())
    assert len(drafts) > 0


def test_real_source_simulated_target_still_attempted():
    world = _world("real", "simulated")
    _, drafts = step(world, _config())
    assert len(drafts) > 0


def test_simulated_source_real_target_still_attempted():
    world = _world("simulated", "real")
    _, drafts = step(world, _config())
    assert len(drafts) > 0
