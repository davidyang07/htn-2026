from app.engine.state import SecurityState
from app.graph.security_graph import PROPAGATION_EDGE_TYPES, SecurityGraph
from app.graph.types import EdgeType, GraphEdge, GraphNode, NodeType


def test_add_and_query_nodes():
    graph = SecurityGraph()
    graph.add_node(GraphNode(id="agent-000", node_type=NodeType.AGENT))
    graph.add_node(GraphNode(id="tool-000", node_type=NodeType.TOOL))

    assert graph.node("agent-000") is not None
    assert graph.node("agent-000").node_type == NodeType.AGENT
    assert graph.node("missing") is None
    assert {n.id for n in graph.nodes} == {"agent-000", "tool-000"}
    assert [n.id for n in graph.nodes_of_type(NodeType.TOOL)] == ["tool-000"]


def test_multiple_edge_types_between_same_pair_coexist():
    graph = SecurityGraph()
    graph.add_node(GraphNode(id="a", node_type=NodeType.AGENT))
    graph.add_node(GraphNode(id="b", node_type=NodeType.AGENT))
    graph.add_edge(GraphEdge(source="a", target="b", edge_type=EdgeType.COMMUNICATES_WITH))
    graph.add_edge(
        GraphEdge(source="a", target="b", edge_type=EdgeType.TRUSTS, attrs={"weight": 0.5})
    )

    edge_types = {e.edge_type for e in graph.edges()}
    assert edge_types == {EdgeType.COMMUNICATES_WITH, EdgeType.TRUSTS}
    trust_edges = graph.edges(edge_types=frozenset({EdgeType.TRUSTS}))
    assert len(trust_edges) == 1
    assert trust_edges[0].attrs["weight"] == 0.5


def test_compromised_ids_reflects_security_state():
    graph = SecurityGraph()
    graph.add_node(
        GraphNode(id="a", node_type=NodeType.AGENT, security_state=SecurityState.COMPROMISED)
    )
    graph.add_node(
        GraphNode(id="b", node_type=NodeType.AGENT, security_state=SecurityState.HEALTHY)
    )

    assert graph.compromised_ids() == {"a"}


def test_subgraph_view_filters_by_edge_type_and_keeps_isolated_nodes():
    graph = SecurityGraph()
    graph.add_node(GraphNode(id="a", node_type=NodeType.AGENT))
    graph.add_node(GraphNode(id="b", node_type=NodeType.AGENT))
    graph.add_node(GraphNode(id="sentinel-000", node_type=NodeType.SENTINEL))
    graph.add_edge(GraphEdge(source="a", target="b", edge_type=EdgeType.COMMUNICATES_WITH))
    graph.add_edge(GraphEdge(source="sentinel-000", target="a", edge_type=EdgeType.MONITORS))

    view = graph.subgraph_view(PROPAGATION_EDGE_TYPES)
    assert set(view.nodes) == {"a", "b", "sentinel-000"}
    assert list(view.edges) == [("a", "b")]
