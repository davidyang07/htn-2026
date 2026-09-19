"""Imports an externally-authored multi-agent topology (e.g. the LangGraph
sample in examples/langgraph_research_agents/) into AgentShield's WorldState/
SecurityGraph shape. This is the "topology import" leg of the real external
integration priority: agent identity and communication edges come straight
from the real app's actual graph structure (via
app/engine/topology.py::build_world_from_agents); tool/credential/resource/
sentinel-count synthetic attachment still comes from ExperimentConfig
exactly as it does for any other experiment (docs/PLAN.md §2.3) --
attach_tool_bindings layers the imported app's *actual* tool ownership on
top of that as additional, real (non-synthetic) CAN_ACCESS edges.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from app.graph.security_graph import SecurityGraph
from app.graph.types import EdgeType, GraphEdge, GraphNode, NodeType


class ExternalTopology(BaseModel):
    agents: list[str]
    edges: list[tuple[str, str]]
    tool_bindings: dict[str, list[str]] = {}
    sentinel_agents: list[str] = []


def load_topology_json(path: Path) -> ExternalTopology:
    return ExternalTopology.model_validate(json.loads(Path(path).read_text()))


def attach_tool_bindings(graph: SecurityGraph, tool_bindings: dict[str, list[str]]) -> None:
    for agent_id, tool_names in sorted(tool_bindings.items()):
        for tool_name in sorted(tool_names):
            tool_id = f"tool-{tool_name}"
            if graph.node(tool_id) is None:
                graph.add_node(GraphNode(id=tool_id, node_type=NodeType.TOOL))
            graph.add_edge(
                GraphEdge(source=agent_id, target=tool_id, edge_type=EdgeType.CAN_ACCESS)
            )


def tag_sentinel_agents(graph: SecurityGraph, sentinel_agents: list[str]) -> None:
    for agent_id in sentinel_agents:
        node = graph.node(agent_id)
        if node is not None:
            node.attrs["imported_role"] = "sentinel"
