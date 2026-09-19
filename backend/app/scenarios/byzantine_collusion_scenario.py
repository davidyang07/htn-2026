"""Byzantine collusion (docs/PLAN.md §5).

Deterministic, rule-based, composable (does NOT own the tick increment).
>=2 COMPROMISED agents coordinate to jointly exceed credential access scope
on a CREDENTIAL neither legitimately holds -- the observable violation
(docs/PLAN.md §2.2) is a POLICY_VIOLATION with
metadata.violation_type = "credential_scope_exceeded". Compromised agents
are paired in deterministic sorted-id order (same tie-break convention as
app/engine/propagation.py::step); each pair is tried against every
CREDENTIAL neither already legitimately uses (via USES_CREDENTIAL), in
sorted credential-id order, stopping at the first successful draw per pair
so output stays bounded per tick. A successful collusion also marks the
credential COMPROMISED (docs/PLAN.md line 84: "a SENTINEL or CREDENTIAL node
can itself become COMPROMISED"), extending blast-radius/privileged-exposure
analysis through it on subsequent builds.

Defaults to a strict no-op (byzantine_collusion_rate == 0.0); needs >= 2
compromised agents and at least one CREDENTIAL node (credential_count > 0).
"""

from __future__ import annotations

from app.engine.rng import rng
from app.engine.state import SecurityState, WorldState
from app.graph.builder import build_security_graph
from app.graph.types import EdgeType, NodeType
from app.schemas.events import EventDraft, EventType
from app.schemas.experiment import ExperimentConfig


def step(state: WorldState, config: ExperimentConfig) -> tuple[WorldState, list[EventDraft]]:
    """Advance Byzantine-collusion for one tick. Pure, synchronous, total."""
    if config.byzantine_collusion_rate <= 0.0:
        return state, []

    compromised = sorted(
        node_id
        for node_id, node in state.nodes.items()
        if node.security_state == SecurityState.COMPROMISED
    )
    if len(compromised) < 2:
        return state, []

    graph = build_security_graph(state, config)
    credentials = sorted(graph.nodes_of_type(NodeType.CREDENTIAL), key=lambda n: n.id)
    if not credentials:
        return state, []

    holders_by_credential: dict[str, set[str]] = {}
    for edge in graph.edges(frozenset({EdgeType.USES_CREDENTIAL})):
        holders_by_credential.setdefault(edge.target, set()).add(edge.source)

    drafts: list[EventDraft] = []
    newly_compromised: set[str] = set(state.compromised_graph_nodes)

    for i in range(0, len(compromised) - 1, 2):
        source, accomplice = compromised[i], compromised[i + 1]
        for credential in credentials:
            holders = holders_by_credential.get(credential.id, set())
            if source in holders or accomplice in holders:
                continue
            draw = rng(
                config.seed, state.tick, credential.id, f"collusion:{source}:{accomplice}"
            ).random()
            if draw < config.byzantine_collusion_rate:
                newly_compromised.add(credential.id)
                drafts.append(
                    EventDraft(
                        sim_tick=state.tick,
                        event_type=EventType.POLICY_VIOLATION,
                        source_agent_id=source,
                        target_agent_id=accomplice,
                        metadata={
                            "violation_type": "credential_scope_exceeded",
                            "credential_id": credential.id,
                            "colluding_agents": [source, accomplice],
                        },
                    )
                )
                break

    if newly_compromised == state.compromised_graph_nodes:
        return state, drafts

    new_state = WorldState(
        tick=state.tick,
        nodes=state.nodes,
        edges=state.edges,
        compromised_graph_nodes=frozenset(newly_compromised),
    )
    return new_state, drafts


class ByzantineCollusionScenario:
    name = "byzantine_collusion"

    def step(
        self, state: WorldState, config: ExperimentConfig
    ) -> tuple[WorldState, list[EventDraft]]:
        return step(state, config)


byzantine_collusion_scenario = ByzantineCollusionScenario()
