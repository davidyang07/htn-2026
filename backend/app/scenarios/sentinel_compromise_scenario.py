"""Sentinel compromise + threat-memory poisoning (docs/PLAN.md §5).

Deterministic, rule-based, composable (does NOT own the tick increment --
unlike propagation/adaptive_attacker, it runs alongside one of those in
`active_scenarios`, mirroring app/security/detection.py::step's own
same-tick, no-increment shape).

Each tick: any SENTINEL that MONITORS at least one currently-COMPROMISED
agent has a `config.sentinel_compromise_rate` chance of itself becoming
COMPROMISED -- the observable violation is a POLICY_VIOLATION event
(metadata.violation_type = "sentinel_subverted"), never an arbitrary state
flip (docs/PLAN.md §2.2). Once compromised, a sentinel demonstrates
threat-memory poisoning every subsequent tick by publishing a
THREAT_SIGNATURE_PUBLISHED with metadata.legitimate=false -- the
mechanically-checkable definition of the poisoning attack succeeding
(docs/PLAN.md §5), matching the precedent already set by false_quarantine's
"AGENT_QUARANTINED with metadata.legitimate=false" definition.

Defaults to a strict no-op (sentinel_compromise_rate == 0.0), so no existing
test's expected output changes.
"""

from __future__ import annotations

from app.engine.rng import rng
from app.engine.state import SecurityState, WorldState
from app.graph.builder import build_security_graph
from app.graph.types import EdgeType, NodeType
from app.schemas.events import EventDraft, EventType
from app.schemas.experiment import ExperimentConfig


def step(state: WorldState, config: ExperimentConfig) -> tuple[WorldState, list[EventDraft]]:
    """Advance sentinel-compromise/threat-memory-poisoning for one tick.
    Pure, synchronous, total. Does not increment state.tick."""
    if config.sentinel_compromise_rate <= 0.0:
        return state, []

    graph = build_security_graph(state, config)
    sentinels = sorted(graph.nodes_of_type(NodeType.SENTINEL), key=lambda n: n.id)
    if not sentinels:
        return state, []

    compromised_agents = {
        node_id
        for node_id, node in state.nodes.items()
        if node.security_state == SecurityState.COMPROMISED
    }
    monitors = graph.edges(frozenset({EdgeType.MONITORS}))
    monitored_by: dict[str, set[str]] = {}
    for edge in monitors:
        monitored_by.setdefault(edge.source, set()).add(edge.target)

    drafts: list[EventDraft] = []
    newly_compromised: set[str] = set(state.compromised_graph_nodes)

    for sentinel in sentinels:
        if sentinel.id in newly_compromised:
            continue
        if not monitored_by.get(sentinel.id, set()) & compromised_agents:
            continue
        draw = rng(config.seed, state.tick, sentinel.id, "sentinel_compromise").random()
        if draw < config.sentinel_compromise_rate:
            newly_compromised.add(sentinel.id)
            drafts.append(
                EventDraft(
                    sim_tick=state.tick,
                    event_type=EventType.POLICY_VIOLATION,
                    agent_id=sentinel.id,
                    metadata={"violation_type": "sentinel_subverted", "sentinel_id": sentinel.id},
                )
            )

    compromised_sentinel_ids = sorted(
        s.id for s in sentinels if s.id in newly_compromised
    )
    for sentinel_id in compromised_sentinel_ids:
        drafts.append(
            EventDraft(
                sim_tick=state.tick,
                event_type=EventType.THREAT_SIGNATURE_PUBLISHED,
                agent_id=sentinel_id,
                metadata={"legitimate": False},
            )
        )

    if newly_compromised == state.compromised_graph_nodes:
        return state, drafts

    new_state = WorldState(
        tick=state.tick,
        nodes=state.nodes,
        edges=state.edges,
        compromised_graph_nodes=frozenset(newly_compromised),
    )
    return new_state, drafts


class SentinelCompromiseScenario:
    name = "sentinel_compromise"

    def step(
        self, state: WorldState, config: ExperimentConfig
    ) -> tuple[WorldState, list[EventDraft]]:
        return step(state, config)


sentinel_compromise_scenario = SentinelCompromiseScenario()
