"""API view models for the security graph and its analysis (docs/PLAN.md
§2.5). Separate from app/graph/types.py's GraphNode/GraphEdge -- those are
internal engine dataclasses; these are the outbound Pydantic contract that
flows through the existing OpenAPI -> schema.d.ts typegen pipeline."""

from typing import Any

from pydantic import BaseModel

from app.engine.state import SecurityState
from app.graph.types import EdgeType, NodeType


class GraphNodeView(BaseModel):
    id: str
    node_type: NodeType
    security_state: SecurityState
    attrs: dict[str, Any]


class GraphEdgeView(BaseModel):
    source: str
    target: str
    edge_type: EdgeType
    attrs: dict[str, Any]


class SecurityGraphView(BaseModel):
    nodes: list[GraphNodeView]
    edges: list[GraphEdgeView]


class AttackPathsResponse(BaseModel):
    paths: list[list[str]]


class BlastRadiusResponse(BaseModel):
    compromised: list[str]
    reachable: list[str]
    fraction: float


class CriticalNodeView(BaseModel):
    id: str
    betweenness: float


class CriticalNodesResponse(BaseModel):
    nodes: list[CriticalNodeView]


class ProvenanceResponse(BaseModel):
    chain: list[str]
