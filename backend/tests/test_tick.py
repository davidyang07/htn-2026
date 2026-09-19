from app.engine.state import AgentNode, SecurityState, WorldState
from app.engine.tick import advance
from app.schemas.experiment import ExperimentConfig


def _two_node_world() -> WorldState:
    nodes = {
        "agent-000": AgentNode(
            id="agent-000",
            software_type="sw-a",
            security_state=SecurityState.COMPROMISED,
            neighbors=("agent-001",),
            compromised_by=None,
            tick_compromised=0,
        ),
        "agent-001": AgentNode(
            id="agent-001",
            software_type="sw-a",
            security_state=SecurityState.HEALTHY,
            neighbors=("agent-000",),
        ),
    }
    edges = (("agent-000", "agent-001"),)
    return WorldState(tick=0, nodes=nodes, edges=edges)


def test_advance_concatenates_propagation_then_security_drafts_in_order():
    world = _two_node_world()
    config = ExperimentConfig(
        seed=42, node_count=25, p_same=1.0, defense_enabled=True, detector_sensitivity=1.0
    )

    new_world, drafts = advance(world, config)

    event_types = [d.event_type.value for d in drafts]
    # propagation drafts (COMPROMISE_*) must precede security drafts
    # (ANOMALY_DETECTED / AGENT_QUARANTINED) within this single advance() call.
    last_propagation_index = max(
        i for i, t in enumerate(event_types) if t.startswith("COMPROMISE_")
    )
    first_security_index = min(
        i for i, t in enumerate(event_types) if t in ("ANOMALY_DETECTED", "AGENT_QUARANTINED")
    )
    assert last_propagation_index < first_security_index

    # detector_sensitivity=1.0 guarantees agent-000 is quarantined this tick.
    assert new_world.nodes["agent-000"].security_state == SecurityState.QUARANTINED


def test_advance_with_defense_disabled_matches_propagation_step_alone():
    from app.engine.propagation import step as propagation_step

    world = _two_node_world()
    config = ExperimentConfig(seed=42, node_count=25, defense_enabled=False)

    expected_world, expected_drafts = propagation_step(world, config)
    actual_world, actual_drafts = advance(world, config)

    assert actual_world == expected_world
    assert actual_drafts == expected_drafts
