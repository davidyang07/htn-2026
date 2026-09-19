from app.engine.state import AgentNode, SecurityState, WorldState
from app.scenarios.adaptive_attacker_scenario import choose_strategy, step
from app.schemas.experiment import ExperimentConfig


def _star_world(center_state=SecurityState.COMPROMISED) -> WorldState:
    # center (degree 3) -- hub, high-degree, low-degree targets both healthy.
    # leaf-a (degree 1), leaf-b (degree 1), leaf-c (degree 1)
    nodes = {
        "agent-000": AgentNode(
            id="agent-000",
            software_type="sw-a",
            security_state=center_state,
            neighbors=("agent-001", "agent-002", "agent-003"),
            compromised_by=None,
            tick_compromised=0 if center_state == SecurityState.COMPROMISED else None,
        ),
        "agent-001": AgentNode(
            id="agent-001",
            software_type="sw-a",
            security_state=SecurityState.HEALTHY,
            neighbors=("agent-000", "agent-004"),
        ),
        "agent-002": AgentNode(
            id="agent-002",
            software_type="sw-a",
            security_state=SecurityState.HEALTHY,
            neighbors=("agent-000",),
        ),
        "agent-003": AgentNode(
            id="agent-003",
            software_type="sw-a",
            security_state=SecurityState.HEALTHY,
            neighbors=("agent-000",),
        ),
        "agent-004": AgentNode(
            id="agent-004",
            software_type="sw-a",
            security_state=SecurityState.HEALTHY,
            neighbors=("agent-001",),
        ),
    }
    edges = (
        ("agent-000", "agent-001"),
        ("agent-000", "agent-002"),
        ("agent-000", "agent-003"),
        ("agent-001", "agent-004"),
    )
    return WorldState(tick=0, nodes=nodes, edges=edges)


def test_default_strategy_is_aggressive_with_no_history():
    world = _star_world()
    config = ExperimentConfig(seed=1, node_count=25)
    assert choose_strategy(world, config) == "aggressive"


def test_aggressive_strategy_targets_the_highest_degree_healthy_neighbor():
    world = _star_world()
    config = ExperimentConfig(seed=1, node_count=25, p_same=1.0)

    _, drafts = step(world, config)

    attempted = [d for d in drafts if d.event_type.value == "COMPROMISE_ATTEMPTED"]
    assert len(attempted) == 1
    # agent-001 has degree 2 (neighbors: agent-000, agent-004); agent-002 and
    # agent-003 have degree 1 -- agent-001 is the highest-degree target.
    assert attempted[0].target_agent_id == "agent-001"
    assert attempted[0].metadata["strategy"] == "aggressive"


def test_stealthy_strategy_targets_a_lowest_degree_healthy_neighbor():
    world = _star_world()
    config = ExperimentConfig(seed=1, node_count=25, p_same=1.0, adaptive_detection_threshold=0.0)

    _, drafts = step(world, config)

    attempted = [d for d in drafts if d.event_type.value == "COMPROMISE_ATTEMPTED"]
    assert len(attempted) == 1
    assert attempted[0].target_agent_id in {"agent-002", "agent-003"}
    assert attempted[0].metadata["strategy"] == "stealthy"


def test_strategy_switches_to_stealthy_once_detection_rate_crosses_threshold():
    nodes = {
        "agent-000": AgentNode(
            id="agent-000",
            software_type="sw-a",
            security_state=SecurityState.COMPROMISED,
            neighbors=("agent-001",),
            compromised_by="agent-999",
            tick_compromised=0,
        ),
        "agent-001": AgentNode(
            id="agent-001",
            software_type="sw-a",
            security_state=SecurityState.QUARANTINED,
            neighbors=("agent-000",),
            compromised_by="agent-000",
            tick_compromised=0,
        ),
    }
    world = WorldState(tick=1, nodes=nodes, edges=(("agent-000", "agent-001"),))
    config = ExperimentConfig(seed=1, node_count=25, adaptive_detection_threshold=0.3)

    assert choose_strategy(world, config) == "stealthy"


def test_success_produces_compromise_succeeded_and_advances_tick():
    world = _star_world()
    config = ExperimentConfig(seed=1, node_count=25, p_same=1.0)

    new_world, drafts = step(world, config)

    event_types = {d.event_type.value for d in drafts}
    assert "COMPROMISE_SUCCEEDED" in event_types
    assert new_world.tick == world.tick + 1
    succeeded = next(d for d in drafts if d.event_type.value == "COMPROMISE_SUCCEEDED")
    assert new_world.nodes[succeeded.target_agent_id].security_state == SecurityState.COMPROMISED
    assert new_world.nodes[succeeded.target_agent_id].compromised_by == "agent-000"


def test_failure_produces_compromise_failed_and_leaves_target_healthy():
    world = _star_world()
    config = ExperimentConfig(seed=1, node_count=25, p_same=0.0, p_cross=0.0)

    new_world, drafts = step(world, config)

    event_types = {d.event_type.value for d in drafts}
    assert event_types == {"COMPROMISE_ATTEMPTED", "COMPROMISE_FAILED"}
    assert all(
        node.security_state != SecurityState.COMPROMISED
        for agent_id, node in new_world.nodes.items()
        if agent_id != "agent-000"
    )


def test_is_deterministic_across_calls():
    world = _star_world()
    config = ExperimentConfig(seed=7, node_count=25, p_same=0.5, p_cross=0.5)

    world_a, drafts_a = step(world, config)
    world_b, drafts_b = step(world, config)

    assert world_a == world_b
    assert drafts_a == drafts_b


def test_no_compromised_source_produces_no_drafts():
    world = _star_world(center_state=SecurityState.HEALTHY)
    config = ExperimentConfig(seed=1, node_count=25)

    new_world, drafts = step(world, config)

    assert drafts == []
    assert new_world.tick == world.tick + 1
