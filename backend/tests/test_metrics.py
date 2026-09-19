from uuid import uuid4

from app.engine.state import AgentNode, SecurityState, WorldState
from app.graph.security_graph import SecurityGraph
from app.graph.types import EdgeType, GraphEdge, GraphNode, NodeType
from app.metrics.compute import (
    attack_success_rate,
    blast_radius_fraction,
    compromise_fraction,
    containment_latency,
    detection_latency,
    false_quarantine_rate,
    privileged_exposure,
    retained_utility,
    security_plane_integrity,
)
from app.schemas.events import Event, EventType


def _event(
    event_type: EventType, *, agent_id: str | None = None, sim_tick: int = 0, **metadata
) -> Event:
    return Event(
        sim_tick=sim_tick,
        event_type=event_type,
        agent_id=agent_id,
        event_id=uuid4(),
        seq=0,
        experiment_id=uuid4(),
        wall_time="2026-01-01T00:00:00Z",
        metadata=metadata,
    )


def _world(states: dict[str, SecurityState]) -> WorldState:
    nodes = {
        n: AgentNode(id=n, software_type="sw-a", security_state=state, neighbors=())
        for n, state in states.items()
    }
    return WorldState(tick=0, nodes=nodes, edges=())


def test_compromise_fraction_and_retained_utility():
    world = _world(
        {
            "a": SecurityState.COMPROMISED,
            "b": SecurityState.QUARANTINED,
            "c": SecurityState.HEALTHY,
            "d": SecurityState.HEALTHY,
        }
    )
    assert compromise_fraction(world) == 0.25
    assert retained_utility(world) == 0.5


def test_empty_world_metrics_are_zero_not_a_division_error():
    world = _world({})
    assert compromise_fraction(world) == 0.0
    assert retained_utility(world) == 0.0


def _graph_with_credential_and_resource(compromised: bool) -> SecurityGraph:
    graph = SecurityGraph()
    state = SecurityState.COMPROMISED if compromised else SecurityState.HEALTHY
    graph.add_node(GraphNode(id="agent-000", node_type=NodeType.AGENT, security_state=state))
    graph.add_node(GraphNode(id="credential-000", node_type=NodeType.CREDENTIAL))
    graph.add_node(GraphNode(id="resource-000", node_type=NodeType.RESOURCE))
    graph.add_edge(
        GraphEdge(source="agent-000", target="credential-000", edge_type=EdgeType.USES_CREDENTIAL)
    )
    graph.add_edge(
        GraphEdge(source="credential-000", target="resource-000", edge_type=EdgeType.CAN_ACCESS)
    )
    return graph


def test_privileged_exposure_counts_reachable_credentials_and_resources():
    graph = _graph_with_credential_and_resource(compromised=True)
    assert privileged_exposure(graph) == 2


def test_privileged_exposure_zero_when_nothing_compromised():
    graph = _graph_with_credential_and_resource(compromised=False)
    assert privileged_exposure(graph) == 0


def test_blast_radius_fraction_counts_agents_only():
    graph = _graph_with_credential_and_resource(compromised=True)
    # 1 compromised agent reaches itself + credential + resource, but the
    # fraction denominator is agent count only (1), so it should be >= 1.0.
    assert blast_radius_fraction(graph) == 1.0


def test_security_plane_integrity_is_one_with_no_plane_nodes():
    graph = SecurityGraph()
    graph.add_node(GraphNode(id="agent-000", node_type=NodeType.AGENT))
    assert security_plane_integrity(graph) == 1.0


def test_security_plane_integrity_reflects_compromised_sentinels():
    graph = SecurityGraph()
    graph.add_node(
        GraphNode(
            id="sentinel-000", node_type=NodeType.SENTINEL, security_state=SecurityState.HEALTHY
        )
    )
    graph.add_node(
        GraphNode(
            id="sentinel-001", node_type=NodeType.SENTINEL, security_state=SecurityState.COMPROMISED
        )
    )
    assert security_plane_integrity(graph) == 0.5


def test_attack_success_rate():
    events = [
        _event(EventType.COMPROMISE_SUCCEEDED),
        _event(EventType.COMPROMISE_SUCCEEDED),
        _event(EventType.COMPROMISE_FAILED),
        _event(EventType.AGENT_CREATED),
    ]
    assert attack_success_rate(events) == 2 / 3


def test_attack_success_rate_zero_with_no_attempts():
    assert attack_success_rate([_event(EventType.AGENT_CREATED)]) == 0.0


def test_false_quarantine_rate():
    events = [
        _event(EventType.AGENT_QUARANTINED, legitimate=False),
        _event(EventType.AGENT_QUARANTINED),
        _event(EventType.ANOMALY_DETECTED),
    ]
    assert false_quarantine_rate(events) == 0.5


def test_false_quarantine_rate_zero_with_no_quarantines():
    assert false_quarantine_rate([_event(EventType.AGENT_CREATED)]) == 0.0


def _node(agent_id: str, tick_compromised: int | None) -> AgentNode:
    state = SecurityState.HEALTHY if tick_compromised is None else SecurityState.COMPROMISED
    return AgentNode(
        id=agent_id,
        software_type="sw-a",
        security_state=state,
        neighbors=(),
        tick_compromised=tick_compromised,
    )


def test_detection_latency_is_none_with_no_detections():
    world = WorldState(tick=0, nodes={"agent-000": _node("agent-000", 3)}, edges=())
    assert detection_latency(world, []) is None


def test_detection_latency_averages_ticks_since_compromise():
    world = WorldState(
        tick=0,
        nodes={"agent-000": _node("agent-000", 3), "agent-001": _node("agent-001", 5)},
        edges=(),
    )
    events = [
        _event(EventType.ANOMALY_DETECTED, agent_id="agent-000", sim_tick=5),
        _event(EventType.ANOMALY_DETECTED, agent_id="agent-001", sim_tick=8),
    ]
    # (5-3) and (8-5) -> mean 2.5
    assert detection_latency(world, events) == 2.5


def test_detection_latency_only_first_detection_counts():
    world = WorldState(tick=0, nodes={"agent-000": _node("agent-000", 3)}, edges=())
    events = [
        _event(EventType.ANOMALY_DETECTED, agent_id="agent-000", sim_tick=5),
        _event(EventType.ANOMALY_DETECTED, agent_id="agent-000", sim_tick=9),
    ]
    assert detection_latency(world, events) == 2.0


def test_detection_latency_ignores_nodes_never_compromised():
    world = WorldState(tick=0, nodes={"agent-000": _node("agent-000", None)}, edges=())
    events = [_event(EventType.ANOMALY_DETECTED, agent_id="agent-000", sim_tick=5)]
    assert detection_latency(world, events) is None


def test_containment_latency_is_none_with_no_quarantines():
    events = [_event(EventType.ANOMALY_DETECTED, agent_id="agent-000", sim_tick=3)]
    assert containment_latency(events) is None


def test_containment_latency_averages_ticks_from_detection_to_quarantine():
    events = [
        _event(EventType.ANOMALY_DETECTED, agent_id="agent-000", sim_tick=3),
        _event(EventType.AGENT_QUARANTINED, agent_id="agent-000", sim_tick=4),
        _event(EventType.ANOMALY_DETECTED, agent_id="agent-001", sim_tick=3),
        _event(EventType.AGENT_QUARANTINED, agent_id="agent-001", sim_tick=6),
    ]
    # (4-3) and (6-3) -> mean 2.0
    assert containment_latency(events) == 2.0


def test_containment_latency_excludes_false_quarantines():
    events = [
        _event(EventType.AGENT_QUARANTINED, agent_id="agent-000", sim_tick=4, legitimate=False),
    ]
    assert containment_latency(events) is None


def test_containment_latency_requires_a_preceding_detection():
    events = [_event(EventType.AGENT_QUARANTINED, agent_id="agent-000", sim_tick=4)]
    assert containment_latency(events) is None
