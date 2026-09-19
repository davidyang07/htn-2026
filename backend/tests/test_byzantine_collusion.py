from app.engine.state import AgentNode, SecurityState, WorldState
from app.graph.builder import build_security_graph
from app.graph.types import EdgeType
from app.scenarios.byzantine_collusion_scenario import step
from app.schemas.experiment import ExperimentConfig


def _world(compromised_count: int = 2, total: int = 4) -> WorldState:
    ids = [f"agent-{i:03d}" for i in range(total)]
    nodes = {}
    for i, agent_id in enumerate(ids):
        state = SecurityState.COMPROMISED if i < compromised_count else SecurityState.HEALTHY
        nodes[agent_id] = AgentNode(
            id=agent_id,
            software_type="sw-a",
            security_state=state,
            neighbors=tuple(x for x in ids if x != agent_id),
            tick_compromised=0 if state == SecurityState.COMPROMISED else None,
        )
    edges = tuple((ids[i], ids[j]) for i in range(total) for j in range(i + 1, total))
    return WorldState(tick=1, nodes=nodes, edges=edges)


def test_zero_rate_is_a_strict_noop():
    world = _world()
    config = ExperimentConfig(seed=42, credential_count=1, byzantine_collusion_rate=0.0)

    new_world, drafts = step(world, config)

    assert drafts == []
    assert new_world == world


def test_fewer_than_two_compromised_agents_is_a_noop():
    world = _world(compromised_count=1)
    config = ExperimentConfig(seed=42, credential_count=1, byzantine_collusion_rate=1.0)

    _, drafts = step(world, config)

    assert drafts == []


def test_no_credentials_is_a_noop():
    world = _world()
    config = ExperimentConfig(seed=42, credential_count=0, byzantine_collusion_rate=1.0)

    _, drafts = step(world, config)

    assert drafts == []


def test_full_rate_produces_a_policy_violation_for_a_colluding_pair():
    world = _world(compromised_count=2, total=4)
    config = ExperimentConfig(seed=42, credential_count=1, byzantine_collusion_rate=1.0)

    new_world, drafts = step(world, config)

    violations = [d for d in drafts if d.event_type.value == "POLICY_VIOLATION"]
    assert len(violations) == 1
    v = violations[0]
    assert v.metadata["violation_type"] == "credential_scope_exceeded"
    assert v.source_agent_id == "agent-000"
    assert v.target_agent_id == "agent-001"
    assert v.metadata["colluding_agents"] == ["agent-000", "agent-001"]
    assert "credential-000" in new_world.compromised_graph_nodes


def test_legitimate_holder_is_never_flagged_as_colluding():
    world = _world(compromised_count=2, total=4)
    config = ExperimentConfig(seed=42, credential_count=1, byzantine_collusion_rate=1.0)
    graph = build_security_graph(world, config)
    holder = next(e.source for e in graph.edges(frozenset({EdgeType.USES_CREDENTIAL})))

    _, drafts = step(world, config)

    violations = [d for d in drafts if d.event_type.value == "POLICY_VIOLATION"]
    for v in violations:
        assert holder not in v.metadata["colluding_agents"]


def test_compromised_credential_is_reflected_in_the_built_graph():
    world = _world()
    config = ExperimentConfig(seed=42, credential_count=1, byzantine_collusion_rate=1.0)

    new_world, _ = step(world, config)
    graph = build_security_graph(new_world, config)

    credential = graph.node("credential-000")
    assert credential is not None
    assert credential.security_state == SecurityState.COMPROMISED


def test_does_not_own_the_tick_increment():
    world = _world()
    config = ExperimentConfig(seed=42, credential_count=1, byzantine_collusion_rate=1.0)

    new_world, _ = step(world, config)

    assert new_world.tick == world.tick


def test_is_deterministic_across_calls():
    world = _world(compromised_count=4, total=8)
    config = ExperimentConfig(seed=7, credential_count=3, byzantine_collusion_rate=0.5)

    world_a, drafts_a = step(world, config)
    world_b, drafts_b = step(world, config)

    assert world_a == world_b
    assert drafts_a == drafts_b
