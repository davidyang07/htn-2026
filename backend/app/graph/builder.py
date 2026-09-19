"""build_security_graph: extends a WorldState (agents + their communication
topology) into a typed SecurityGraph with tools, credentials, resources,
and sentinels/security controls (docs/PLAN.md §2.2/§2.3). Deterministic
function of (state, config) alone -- every attachment decision is keyed
through app/engine/rng.py::rng() exactly like topology.py's
_generate_confidential_token and _select_real_agents, so the identical
typed graph can always be recomputed from a persisted config at replay
time with no separate persistence for graph structure.
"""

from __future__ import annotations

from app.engine.rng import rng
from app.engine.state import SecurityState, WorldState
from app.graph.security_graph import SecurityGraph
from app.graph.types import EdgeType, GraphEdge, GraphNode, NodeType
from app.schemas.experiment import ExperimentConfig


def _state_for(node_id: str, compromised_graph_nodes: frozenset[str]) -> SecurityState:
    """Non-agent graph nodes (tools, credentials, sentinels, ...) have no
    WorldState-resident dataclass of their own -- WorldState.compromised_graph_nodes
    is their compromise record (docs/PLAN.md §5)."""
    if node_id in compromised_graph_nodes:
        return SecurityState.COMPROMISED
    return SecurityState.HEALTHY


def build_security_graph(state: WorldState, config: ExperimentConfig) -> SecurityGraph:
    graph = SecurityGraph()
    sorted_agent_ids = sorted(state.nodes)

    for agent_id in sorted_agent_ids:
        node = state.nodes[agent_id]
        graph.add_node(
            GraphNode(
                id=agent_id,
                node_type=NodeType.AGENT,
                security_state=node.security_state,
                attrs={"software_type": node.software_type, "agent_kind": node.agent_kind},
            )
        )

    for a, b in state.edges:
        graph.add_edge(GraphEdge(source=a, target=b, edge_type=EdgeType.COMMUNICATES_WITH))
        graph.add_edge(GraphEdge(source=b, target=a, edge_type=EdgeType.COMMUNICATES_WITH))
        # Default trust mirrors direct communication topology (weight 1.0):
        # a structural starting point later scenarios can manipulate, not an
        # empirical claim about the agents' actual behavior.
        graph.add_edge(
            GraphEdge(source=a, target=b, edge_type=EdgeType.TRUSTS, attrs={"weight": 1.0})
        )
        graph.add_edge(
            GraphEdge(source=b, target=a, edge_type=EdgeType.TRUSTS, attrs={"weight": 1.0})
        )

    _attach_tools(graph, sorted_agent_ids, config)
    _attach_credentials_and_resources(
        graph, sorted_agent_ids, config, state.compromised_graph_nodes
    )
    _attach_security_plane(graph, sorted_agent_ids, config, state.compromised_graph_nodes)

    return graph


def _attach_tools(graph: SecurityGraph, agent_ids: list[str], config: ExperimentConfig) -> None:
    if config.tool_count <= 0 or not agent_ids:
        return
    accessors_per_tool = max(1, len(agent_ids) // config.tool_count)
    for i in range(config.tool_count):
        tool_id = f"tool-{i:03d}"
        graph.add_node(GraphNode(id=tool_id, node_type=NodeType.TOOL))
        draw = rng(config.seed, 0, tool_id, "tool_access")
        accessors = draw.sample(agent_ids, k=min(len(agent_ids), accessors_per_tool))
        for agent_id in sorted(accessors):
            graph.add_edge(
                GraphEdge(source=agent_id, target=tool_id, edge_type=EdgeType.CAN_ACCESS)
            )


def _attach_credentials_and_resources(
    graph: SecurityGraph,
    agent_ids: list[str],
    config: ExperimentConfig,
    compromised_graph_nodes: frozenset[str],
) -> None:
    if not agent_ids:
        return
    for i in range(config.resource_count):
        graph.add_node(GraphNode(id=f"resource-{i:03d}", node_type=NodeType.RESOURCE))

    for i in range(config.credential_count):
        credential_id = f"credential-{i:03d}"
        graph.add_node(
            GraphNode(
                id=credential_id,
                node_type=NodeType.CREDENTIAL,
                security_state=_state_for(credential_id, compromised_graph_nodes),
            )
        )
        draw = rng(config.seed, 0, credential_id, "credential_holder")
        holder = draw.choice(agent_ids)
        graph.add_edge(
            GraphEdge(source=holder, target=credential_id, edge_type=EdgeType.USES_CREDENTIAL)
        )
        if config.resource_count > 0:
            resource_id = f"resource-{i % config.resource_count:03d}"
            graph.add_edge(
                GraphEdge(source=credential_id, target=resource_id, edge_type=EdgeType.CAN_ACCESS)
            )


def _attach_security_plane(
    graph: SecurityGraph,
    agent_ids: list[str],
    config: ExperimentConfig,
    compromised_graph_nodes: frozenset[str],
) -> None:
    if config.sentinel_count <= 0 or not agent_ids:
        return

    for kind, control_id in (
        ("trust_manager", "control-trust-manager"),
        ("threat_memory_store", "control-threat-memory"),
        ("attestation_service", "control-attestation"),
        ("quarantine_authority", "control-quarantine"),
    ):
        graph.add_node(
            GraphNode(
                id=control_id,
                node_type=NodeType.SECURITY_CONTROL,
                security_state=_state_for(control_id, compromised_graph_nodes),
                attrs={"kind": kind},
            )
        )

    for agent_id in agent_ids:
        graph.add_edge(
            GraphEdge(
                source="control-quarantine",
                target=agent_id,
                edge_type=EdgeType.QUARANTINE_AUTHORITY,
            )
        )

    for i in range(config.sentinel_count):
        sentinel_id = f"sentinel-{i:03d}"
        graph.add_node(
            GraphNode(
                id=sentinel_id,
                node_type=NodeType.SENTINEL,
                security_state=_state_for(sentinel_id, compromised_graph_nodes),
            )
        )
        graph.add_edge(
            GraphEdge(
                source=sentinel_id,
                target="control-threat-memory",
                edge_type=EdgeType.UPDATES_THREAT_MEMORY,
            )
        )
        graph.add_edge(
            GraphEdge(
                source="control-threat-memory",
                target=sentinel_id,
                edge_type=EdgeType.UPDATES_THREAT_MEMORY,
            )
        )

    # Monitoring responsibility is split evenly across sentinels, round-robin
    # over sorted agent ids -- deterministic, no rng draw needed since it's a
    # structural partition, not a probabilistic choice.
    for index, agent_id in enumerate(agent_ids):
        sentinel_id = f"sentinel-{index % config.sentinel_count:03d}"
        graph.add_edge(
            GraphEdge(source=sentinel_id, target=agent_id, edge_type=EdgeType.MONITORS)
        )
