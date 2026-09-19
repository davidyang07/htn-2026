from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class SecurityState(StrEnum):
    HEALTHY = "healthy"
    SUSPICIOUS = "suspicious"
    COMPROMISED = "compromised"
    QUARANTINED = "quarantined"
    RECOVERED = "recovered"


@dataclass
class AgentNode:
    id: str
    software_type: str
    security_state: SecurityState
    neighbors: tuple[str, ...]
    compromised_by: str | None = None
    tick_compromised: int | None = None
    # Phase 2 (docs/PHASE_2_PLAN.md §4): "real" nodes are LLM-backed via the
    # Model Gateway; "simulated" (the default) keeps the pre-Phase-2
    # probabilistic behavior byte-for-byte unchanged. confidential_token is
    # the synthetic secret a real agent must never leak (§6) -- engine-
    # internal only, never added to NodeView or any other outbound schema.
    agent_kind: Literal["simulated", "real"] = "simulated"
    confidential_token: str | None = None


@dataclass
class WorldState:
    tick: int
    nodes: dict[str, AgentNode]
    edges: tuple[tuple[str, str], ...]
    # Byzantine/security-plane attacks (docs/PLAN.md §5): ids of non-agent
    # security-graph nodes (SENTINEL, SECURITY_CONTROL, CREDENTIAL, ...)
    # currently compromised. Agent compromise stays tracked on AgentNode
    # itself (unchanged); this set exists because those node kinds have no
    # WorldState-resident dataclass of their own -- app/graph/builder.py
    # reads it to set a GraphNode's security_state, exactly mirroring how it
    # already reads AgentNode.security_state for AGENT nodes. Defaults to
    # empty, so every existing WorldState() call site is unaffected.
    compromised_graph_nodes: frozenset[str] = frozenset()
