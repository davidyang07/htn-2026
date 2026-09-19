"""Typed security-graph domain model (docs/PLAN.md §2.2): the node and edge
kinds an agent ecosystem is actually made of -- agents, tools/MCP servers,
credentials, resources, memory, sentinels, and security controls -- plus the
relationships between them. Kept as plain dataclasses (mirrors
app/engine/state.py::AgentNode's style) rather than a class hierarchy per
type: one shape with a generic `attrs` dict for type-specific data is the
same pattern already used for event metadata, and this graph has few enough
fields per type that subclassing would add indirection without adding safety.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.engine.state import SecurityState


class NodeType(StrEnum):
    AGENT = "agent"
    TOOL = "tool"
    MCP_SERVER = "mcp_server"
    CREDENTIAL = "credential"
    RESOURCE = "resource"
    MEMORY_STORE = "memory_store"
    SENTINEL = "sentinel"
    SECURITY_CONTROL = "security_control"


class EdgeType(StrEnum):
    COMMUNICATES_WITH = "communicates_with"
    DELEGATES_TO = "delegates_to"
    TRUSTS = "trusts"
    CAN_ACCESS = "can_access"
    USES_CREDENTIAL = "uses_credential"
    MONITORS = "monitors"
    QUARANTINE_AUTHORITY = "quarantine_authority"
    UPDATES_THREAT_MEMORY = "updates_threat_memory"


@dataclass
class GraphNode:
    id: str
    node_type: NodeType
    security_state: SecurityState = SecurityState.HEALTHY
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    source: str
    target: str
    edge_type: EdgeType
    attrs: dict[str, Any] = field(default_factory=dict)
