from app.engine.state import AgentNode
from app.engine.topology import build_world
from app.schemas.experiment import ExperimentConfig, NodeView


def test_real_agent_count_zero_means_no_real_nodes():
    config = ExperimentConfig(seed=42, node_count=30, real_agent_count=0)
    world, _ = build_world(config)
    assert all(n.agent_kind == "simulated" for n in world.nodes.values())
    assert all(n.confidential_token is None for n in world.nodes.values())


def test_real_agents_are_highest_degree_nodes():
    config = ExperimentConfig(seed=42, node_count=40, edge_density=3, real_agent_count=5)
    world, _ = build_world(config)

    degree = {n.id: len(n.neighbors) for n in world.nodes.values()}
    expected = set(sorted(degree, key=lambda n: (-degree[n], n))[:5])
    actual = {n.id for n in world.nodes.values() if n.agent_kind == "real"}

    assert actual == expected
    assert len(actual) == 5


def test_real_agents_get_confidential_token_simulated_do_not():
    config = ExperimentConfig(seed=42, node_count=30, real_agent_count=4)
    world, _ = build_world(config)

    for node in world.nodes.values():
        if node.agent_kind == "real":
            assert node.confidential_token is not None
            assert node.confidential_token.startswith("TOKEN-")
        else:
            assert node.confidential_token is None


def test_confidential_token_deterministic_per_seed():
    config = ExperimentConfig(seed=7, node_count=30, real_agent_count=4)
    world_a, _ = build_world(config)
    world_b, _ = build_world(config)

    tokens_a = {
        n.id: n.confidential_token for n in world_a.nodes.values() if n.agent_kind == "real"
    }
    tokens_b = {
        n.id: n.confidential_token for n in world_b.nodes.values() if n.agent_kind == "real"
    }
    assert tokens_a == tokens_b
    assert all(tokens_a.values())  # non-empty, non-None


def test_confidential_tokens_are_unique_per_agent():
    config = ExperimentConfig(seed=7, node_count=60, real_agent_count=10)
    world, _ = build_world(config)
    tokens = [n.confidential_token for n in world.nodes.values() if n.agent_kind == "real"]
    assert len(tokens) == len(set(tokens))


def test_real_agent_count_clamped_le_20_by_schema():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExperimentConfig(seed=1, node_count=30, real_agent_count=21)


def test_node_view_never_exposes_confidential_token():
    """The whole prompt-injection scenario depends on this secret never
    reaching a client (docs/PHASE_2_PLAN.md §4/§11) -- verified structurally,
    not just by omission from the schema definition."""
    assert "confidential_token" not in NodeView.model_fields

    config = ExperimentConfig(seed=42, node_count=30, real_agent_count=4)
    world, _ = build_world(config)
    real_node = next(n for n in world.nodes.values() if n.agent_kind == "real")
    assert isinstance(real_node, AgentNode)
    assert real_node.confidential_token is not None

    view = NodeView(
        id=real_node.id,
        software_type=real_node.software_type,
        security_state=real_node.security_state,
        compromised_by=real_node.compromised_by,
        tick_compromised=real_node.tick_compromised,
        agent_kind=real_node.agent_kind,
    )
    dumped = view.model_dump_json()
    assert real_node.confidential_token not in dumped
    assert "confidential_token" not in dumped
