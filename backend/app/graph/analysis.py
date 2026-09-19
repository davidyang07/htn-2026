"""Pure analysis functions over a SecurityGraph (docs/PLAN.md §2.2/§2.5):
attack-path/reachability, blast radius, critical nodes/choke points, and
compromise provenance. Every function is a pure function of its inputs --
no I/O, no randomness -- so results are reproducible from a persisted
config the same way the rest of the engine is (docs/PLAN.md §2.3).
"""

from __future__ import annotations

import networkx as nx

from app.graph.security_graph import PROPAGATION_EDGE_TYPES, SecurityGraph

# Longest path this enumeration will consider, in hops. `max_paths` alone
# bounds the *output* but not the *search*: nx.all_simple_paths is a DFS, so on
# a dense mesh it can explore an astronomically large subtree before it happens
# to reach the target even once. That is unbounded CPU inside a request, so the
# depth is bounded too. Six hops is well past the point where a longer lateral
# chain tells an operator anything new, and comfortably covers
# agent -> ... -> agent -> credential -> resource.
MAX_PATH_HOPS = 6


def attack_paths(
    graph: SecurityGraph, source: str, target: str, *, max_paths: int = 10
) -> list[list[str]]:
    """Simple (no repeated node) paths of at most MAX_PATH_HOPS hops from
    source to target across propagation-capable edges, in the order networkx
    enumerates them, capped at max_paths so a dense graph can't return an
    unbounded list."""
    view = graph.subgraph_view(PROPAGATION_EDGE_TYPES)
    if source not in view or target not in view:
        return []
    paths: list[list[str]] = []
    for path in nx.all_simple_paths(view, source, target, cutoff=MAX_PATH_HOPS):
        paths.append(path)
        if len(paths) >= max_paths:
            break
    return paths


def blast_radius(graph: SecurityGraph) -> set[str]:
    """Every node reachable from a currently-compromised node across
    propagation-capable edges, including the compromised nodes themselves."""
    view = graph.subgraph_view(PROPAGATION_EDGE_TYPES)
    compromised = graph.compromised_ids() & set(view.nodes)
    reachable: set[str] = set(compromised)
    for node_id in compromised:
        reachable |= nx.descendants(view, node_id)
    return reachable


def critical_nodes(graph: SecurityGraph, *, top_n: int = 5) -> list[tuple[str, float]]:
    """Nodes ranked by betweenness centrality over the undirected
    propagation-capable subgraph -- high-betweenness nodes are choke points
    whose removal (quarantine, credential revocation) most disconnects the
    rest of the reachability graph. Ties broken by node id for a stable,
    reproducible ordering."""
    view = graph.subgraph_view(PROPAGATION_EDGE_TYPES).to_undirected()
    if view.number_of_nodes() == 0:
        return []
    centrality = nx.betweenness_centrality(view)
    ranked = sorted(centrality.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:top_n]


def provenance(compromised_by: dict[str, str | None], node_id: str) -> list[str]:
    """Backtrace the compromise chain from node_id to its ultimate (patient
    zero) source, using the same `compromised_by` convention already carried
    by AgentNode (app/engine/topology.py, app/engine/propagation.py). Starts
    with node_id itself; stops at a node with no recorded source or if a
    node would repeat (defensive against a malformed/cyclic map -- a
    well-formed compromise chain is always acyclic by construction)."""
    chain = [node_id]
    seen = {node_id}
    current = node_id
    while True:
        source = compromised_by.get(current)
        if source is None or source in seen:
            break
        chain.append(source)
        seen.add(source)
        current = source
    return chain
