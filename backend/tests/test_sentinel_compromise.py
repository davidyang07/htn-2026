from dataclasses import replace

from app.engine.rng import rng
from app.engine.state import AgentNode, SecurityState, WorldState
from app.graph.builder import build_security_graph
from app.graph.types import NodeType
from app.scenarios.sentinel_compromise_scenario import step
from app.schemas.experiment import ExperimentConfig
from app.security import detection


def _world(count: int = 4, *, first_compromised: bool = True) -> WorldState:
    nodes = {}
    ids = [f"agent-{i:03d}" for i in range(count)]
    for i, agent_id in enumerate(ids):
        is_compromised = i == 0 and first_compromised
        state = SecurityState.COMPROMISED if is_compromised else SecurityState.HEALTHY
        nodes[agent_id] = AgentNode(
            id=agent_id,
            software_type="sw-a",
            security_state=state,
            neighbors=tuple(x for x in ids if x != agent_id),
            tick_compromised=0 if state == SecurityState.COMPROMISED else None,
        )
    edges = tuple((ids[i], ids[j]) for i in range(count) for j in range(i + 1, count))
    return WorldState(tick=1, nodes=nodes, edges=edges)


def test_zero_rate_is_a_strict_noop():
    world = _world()
    config = ExperimentConfig(seed=42, sentinel_count=1, sentinel_compromise_rate=0.0)

    new_world, drafts = step(world, config)

    assert drafts == []
    assert new_world == world


def test_no_sentinels_is_a_noop_even_with_nonzero_rate():
    world = _world()
    config = ExperimentConfig(seed=42, sentinel_count=0, sentinel_compromise_rate=1.0)

    new_world, drafts = step(world, config)

    assert drafts == []
    assert new_world == world


def test_full_rate_compromises_a_sentinel_monitoring_a_compromised_agent():
    world = _world()
    config = ExperimentConfig(seed=42, sentinel_count=1, sentinel_compromise_rate=1.0)

    new_world, drafts = step(world, config)

    assert "sentinel-000" in new_world.compromised_graph_nodes
    violation = [d for d in drafts if d.event_type.value == "POLICY_VIOLATION"]
    assert len(violation) == 1
    assert violation[0].metadata["violation_type"] == "sentinel_subverted"
    assert violation[0].agent_id == "sentinel-000"


def test_sentinel_not_monitoring_any_compromised_agent_stays_healthy():
    world = _world(first_compromised=False)
    config = ExperimentConfig(seed=42, sentinel_count=1, sentinel_compromise_rate=1.0)

    new_world, drafts = step(world, config)

    assert new_world.compromised_graph_nodes == frozenset()
    assert drafts == []


def test_compromised_sentinel_publishes_a_false_threat_signature_every_tick():
    world = _world()
    world = WorldState(
        tick=world.tick,
        nodes=world.nodes,
        edges=world.edges,
        compromised_graph_nodes=frozenset({"sentinel-000"}),
    )
    config = ExperimentConfig(seed=42, sentinel_count=1, sentinel_compromise_rate=1.0)

    new_world, drafts = step(world, config)

    published = [d for d in drafts if d.event_type.value == "THREAT_SIGNATURE_PUBLISHED"]
    assert len(published) == 1
    assert published[0].agent_id == "sentinel-000"
    assert published[0].metadata == {"legitimate": False}
    # Already compromised -- no second POLICY_VIOLATION.
    assert not [d for d in drafts if d.event_type.value == "POLICY_VIOLATION"]
    assert new_world.compromised_graph_nodes == frozenset({"sentinel-000"})


def test_compromised_sentinel_is_reflected_in_the_built_graph():
    world = _world()
    config = ExperimentConfig(seed=42, sentinel_count=1, sentinel_compromise_rate=1.0)
    new_world, _ = step(world, config)

    graph = build_security_graph(new_world, ExperimentConfig(seed=42, sentinel_count=1))
    sentinel = graph.node("sentinel-000")
    assert sentinel is not None
    assert sentinel.security_state == SecurityState.COMPROMISED


def test_is_deterministic_across_calls():
    world = _world(count=6)
    config = ExperimentConfig(seed=7, sentinel_count=2, sentinel_compromise_rate=0.5)

    world_a, drafts_a = step(world, config)
    world_b, drafts_b = step(world, config)

    assert world_a == world_b
    assert drafts_a == drafts_b


def test_is_keyed_deterministically():
    world = _world()
    config = ExperimentConfig(seed=42, sentinel_count=1, sentinel_compromise_rate=0.5)

    expected = rng(config.seed, world.tick, "sentinel-000", "sentinel_compromise").random() < 0.5

    new_world, _ = step(world, config)

    assert ("sentinel-000" in new_world.compromised_graph_nodes) == expected


def test_does_not_own_the_tick_increment():
    world = _world()
    config = ExperimentConfig(seed=42, sentinel_count=1, sentinel_compromise_rate=1.0)

    new_world, _ = step(world, config)

    assert new_world.tick == world.tick


def test_detection_suppresses_anomaly_for_agents_monitored_by_a_compromised_sentinel():
    world = _world()
    world = WorldState(
        tick=world.tick,
        nodes=world.nodes,
        edges=world.edges,
        compromised_graph_nodes=frozenset({"sentinel-000"}),
    )
    config = ExperimentConfig(
        seed=42, sentinel_count=1, defense_enabled=True, detector_sensitivity=1.0
    )

    new_world, drafts = detection.step(world, config)

    assert drafts == []
    assert new_world == world


def test_detection_still_fires_when_no_sentinel_is_compromised():
    world = _world()
    config = ExperimentConfig(
        seed=42, sentinel_count=1, defense_enabled=True, detector_sensitivity=1.0
    )

    _, drafts = detection.step(world, config)

    assert any(d.event_type.value == "ANOMALY_DETECTED" for d in drafts)


def test_more_sentinels_shrink_the_suppressed_fraction_from_one_compromised_sentinel():
    """Causal basis for a future sentinel_count remediation recommendation:
    spreading monitoring across more sentinels shrinks the blast radius of a
    single subverted sentinel's detection suppression -- observed here as
    more ANOMALY_DETECTED events surviving suppression with more sentinels,
    all else equal."""
    all_compromised = _world(count=10)
    all_compromised = WorldState(
        tick=all_compromised.tick,
        nodes={
            agent_id: replace(node, security_state=SecurityState.COMPROMISED, tick_compromised=0)
            for agent_id, node in all_compromised.nodes.items()
        },
        edges=all_compromised.edges,
        compromised_graph_nodes=frozenset({"sentinel-000"}),
    )
    config_one_sentinel = ExperimentConfig(
        seed=42, sentinel_count=1, defense_enabled=True, detector_sensitivity=1.0
    )
    config_five_sentinels = ExperimentConfig(
        seed=42, sentinel_count=5, defense_enabled=True, detector_sensitivity=1.0
    )

    _, drafts_one = detection.step(all_compromised, config_one_sentinel)
    _, drafts_five = detection.step(all_compromised, config_five_sentinels)

    detected_one = {d.agent_id for d in drafts_one if d.event_type.value == "ANOMALY_DETECTED"}
    detected_five = {d.agent_id for d in drafts_five if d.event_type.value == "ANOMALY_DETECTED"}

    assert len(detected_five) > len(detected_one)


def test_zero_sentinel_count_graph_has_no_sentinels_to_compromise():
    world = _world()
    graph = build_security_graph(world, ExperimentConfig(seed=42, sentinel_count=0))
    assert not graph.nodes_of_type(NodeType.SENTINEL)
