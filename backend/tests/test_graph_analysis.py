from app.engine.state import SecurityState
from app.graph.analysis import (
    MAX_PATH_HOPS,
    attack_paths,
    blast_radius,
    critical_nodes,
    provenance,
)
from app.graph.security_graph import SecurityGraph
from app.graph.types import EdgeType, GraphEdge, GraphNode, NodeType


def _agent(graph: SecurityGraph, node_id: str, state=SecurityState.HEALTHY) -> None:
    graph.add_node(GraphNode(id=node_id, node_type=NodeType.AGENT, security_state=state))


def _diamond() -> SecurityGraph:
    # a -> b -> d
    # a -> c -> d
    graph = SecurityGraph()
    for node_id in ("a", "b", "c", "d"):
        _agent(graph, node_id)
    for source, target in (("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")):
        graph.add_edge(
            GraphEdge(source=source, target=target, edge_type=EdgeType.COMMUNICATES_WITH)
        )
    return graph


def test_attack_paths_finds_both_simple_paths_in_a_diamond():
    graph = _diamond()
    paths = attack_paths(graph, "a", "d")
    assert sorted(paths) == [["a", "b", "d"], ["a", "c", "d"]]


def test_attack_paths_empty_when_source_or_target_missing():
    graph = _diamond()
    assert attack_paths(graph, "a", "missing") == []
    assert attack_paths(graph, "missing", "d") == []


def test_attack_paths_respects_max_paths_cap():
    graph = _diamond()
    assert len(attack_paths(graph, "a", "d", max_paths=1)) == 1


def test_attack_paths_stops_at_the_hop_bound():
    # A straight chain of MAX_PATH_HOPS + 1 hops: the only path between the
    # ends is one hop too long, so nothing is returned. The bound exists
    # because all_simple_paths is a DFS with no depth limit of its own --
    # without it, a dense mesh can burn unbounded CPU inside one request.
    graph = SecurityGraph()
    chain = [f"n{i}" for i in range(MAX_PATH_HOPS + 2)]
    for node_id in chain:
        _agent(graph, node_id)
    for source, target in zip(chain, chain[1:], strict=False):
        graph.add_edge(
            GraphEdge(source=source, target=target, edge_type=EdgeType.COMMUNICATES_WITH)
        )

    assert attack_paths(graph, chain[0], chain[MAX_PATH_HOPS]) == [chain[: MAX_PATH_HOPS + 1]]
    assert attack_paths(graph, chain[0], chain[-1]) == []


def test_attack_paths_ignores_non_propagation_edges():
    graph = SecurityGraph()
    _agent(graph, "sentinel-000")
    _agent(graph, "a")
    graph.add_edge(GraphEdge(source="sentinel-000", target="a", edge_type=EdgeType.MONITORS))
    assert attack_paths(graph, "sentinel-000", "a") == []


def test_blast_radius_reaches_only_descendants_of_compromised_nodes():
    graph = _diamond()
    graph.node("a").security_state = SecurityState.COMPROMISED
    assert blast_radius(graph) == {"a", "b", "c", "d"}


def test_blast_radius_empty_when_nothing_compromised():
    graph = _diamond()
    assert blast_radius(graph) == set()


def test_blast_radius_does_not_cross_upstream():
    graph = _diamond()
    graph.node("d").security_state = SecurityState.COMPROMISED
    assert blast_radius(graph) == {"d"}


def test_critical_nodes_ranks_the_bridge_highest():
    # a - b - c : b is the sole articulation point / highest betweenness node.
    graph = SecurityGraph()
    for node_id in ("a", "b", "c"):
        _agent(graph, node_id)
    graph.add_edge(GraphEdge(source="a", target="b", edge_type=EdgeType.COMMUNICATES_WITH))
    graph.add_edge(GraphEdge(source="b", target="c", edge_type=EdgeType.COMMUNICATES_WITH))

    ranked = critical_nodes(graph, top_n=1)
    assert ranked[0][0] == "b"
    assert ranked[0][1] > 0


def test_critical_nodes_empty_graph():
    assert critical_nodes(SecurityGraph()) == []


def test_provenance_backtraces_full_chain():
    compromised_by = {"c": "b", "b": "a", "a": None}
    assert provenance(compromised_by, "c") == ["c", "b", "a"]


def test_provenance_single_node_with_no_source():
    assert provenance({"a": None}, "a") == ["a"]


def test_provenance_is_cycle_safe():
    compromised_by = {"a": "b", "b": "a"}
    assert provenance(compromised_by, "a") == ["a", "b"]
