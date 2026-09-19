from app.engine.rng import rng
from app.engine.state import SecurityState
from app.engine.topology import build_world
from app.schemas.experiment import ExperimentConfig


def _compromised_node(world) -> str:
    compromised = [
        node_id
        for node_id, node in world.nodes.items()
        if node.security_state == SecurityState.COMPROMISED
    ]
    assert len(compromised) == 1
    return compromised[0]


def test_default_strategy_matches_explicit_highest_degree():
    default_config = ExperimentConfig(seed=42, node_count=25)
    explicit_config = ExperimentConfig(seed=42, node_count=25, initial_compromised="highest_degree")

    default_world, default_drafts = build_world(default_config)
    explicit_world, explicit_drafts = build_world(explicit_config)

    assert default_world == explicit_world
    assert default_drafts == explicit_drafts


def test_random_node_strategy_selects_via_keyed_rng():
    config = ExperimentConfig(seed=42, node_count=25, initial_compromised="random_node")
    world, drafts = build_world(config)

    sorted_ids = sorted(world.nodes.keys())
    expected = rng(config.seed, 0, "topology", "initial_compromise").choice(sorted_ids)

    assert _compromised_node(world) == expected
    seeded_drafts = [d for d in drafts if d.metadata.get("initial_compromise")]
    assert len(seeded_drafts) == 1
    assert seeded_drafts[0].target_agent_id == expected


def test_random_node_strategy_is_deterministic_across_calls():
    config = ExperimentConfig(seed=99, node_count=30, initial_compromised="random_node")
    world_a, _ = build_world(config)
    world_b, _ = build_world(config)
    assert _compromised_node(world_a) == _compromised_node(world_b)
