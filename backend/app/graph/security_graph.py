"""SecurityGraph: a typed multi-relational graph over the domain model in
types.py. Wraps networkx.MultiDiGraph rather than a plain DiGraph because
more than one edge type can legitimately exist between the same ordered
pair (e.g. an agent can both COMMUNICATES_WITH and TRUSTS the same
neighbor) -- a MultiDiGraph is what lets those coexist without one
overwriting the other.
"""

from __future__ import annotations

import networkx as nx

from app.engine.state import SecurityState
from app.graph.types import EdgeType, GraphEdge, GraphNode, NodeType

# Edge types an attacker can move laterally across when computing reachability
# (attack paths / blast radius / privileged exposure). MONITORS,
# QUARANTINE_AUTHORITY, TRUSTS, and UPDATES_THREAT_MEMORY describe who
# observes or governs a node, not a channel compromise can travel through.
PROPAGATION_EDGE_TYPES = frozenset(
    {
        EdgeType.COMMUNICATES_WITH,
        EdgeType.DELEGATES_TO,
        EdgeType.CAN_ACCESS,
        EdgeType.USES_CREDENTIAL,
    }
)


class SecurityGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._graph: nx.MultiDiGraph = nx.MultiDiGraph()

    def add_node(self, node: GraphNode) -> None:
        self._nodes[node.id] = node
        self._graph.add_node(node.id)

    def add_edge(self, edge: GraphEdge) -> None:
        self._graph.add_edge(
            edge.source, edge.target, key=edge.edge_type, edge_type=edge.edge_type, **edge.attrs
        )

    def node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    @property
    def nodes(self) -> list[GraphNode]:
        return list(self._nodes.values())

    def nodes_of_type(self, node_type: NodeType) -> list[GraphNode]:
        return [n for n in self._nodes.values() if n.node_type == node_type]

    def edges(self, edge_types: frozenset[EdgeType] | None = None) -> list[GraphEdge]:
        result: list[GraphEdge] = []
        for u, v, data in self._graph.edges(data=True):
            edge_type = data["edge_type"]
            if edge_types is not None and edge_type not in edge_types:
                continue
            attrs = {k: val for k, val in data.items() if k != "edge_type"}
            result.append(GraphEdge(source=u, target=v, edge_type=edge_type, attrs=attrs))
        return result

    def subgraph_view(self, edge_types: frozenset[EdgeType]) -> nx.DiGraph:
        """A simple (non-multi) directed view containing every graph node but
        only edges of the given types -- the shape nx's path/centrality
        algorithms expect. Isolated nodes are kept so blast_radius/attack_paths
        callers can still look up a node with no matching-type edges."""
        view: nx.DiGraph = nx.DiGraph()
        view.add_nodes_from(self._graph.nodes)
        for u, v, data in self._graph.edges(data=True):
            if data["edge_type"] in edge_types:
                view.add_edge(u, v)
        return view

    def compromised_ids(self) -> set[str]:
        return {n.id for n in self._nodes.values() if n.security_state == SecurityState.COMPROMISED}
