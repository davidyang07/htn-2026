"""Deterministic, rule-based adaptive attacker (docs/PLAN.md §4):

observe  -- this tick's quarantine rate among nodes it has ever compromised
choose   -- "stealthy" once that rate reaches config.adaptive_detection_threshold,
            "aggressive" otherwise
attack   -- one attempt per compromised source per tick (unlike
            app/engine/propagation.py's "attempt every healthy neighbor"):
            aggressive targets the highest-degree healthy neighbor to
            maximize spread, stealthy the lowest-degree one to reduce
            detection odds
adapt    -- next tick recomputes strategy fresh from the then-current
            state; the state itself is the memory, so no separate
            persisted attacker-state field is needed

This is an alternative attacker model to propagation_scenario, not a
supplement to it: both own the sim_tick increment (mirroring
app/engine/propagation.py::step exactly), so an experiment should select
one or the other in active_scenarios, never both.
"""

from __future__ import annotations

from dataclasses import replace

from app.engine.rng import rng
from app.engine.state import SecurityState, WorldState
from app.schemas.events import EventDraft, EventType
from app.schemas.experiment import ExperimentConfig


def _detection_rate(state: WorldState) -> float:
    attacked = [
        node
        for node in state.nodes.values()
        if node.compromised_by is not None
        and node.security_state in (SecurityState.COMPROMISED, SecurityState.QUARANTINED)
    ]
    if not attacked:
        return 0.0
    quarantined = sum(1 for node in attacked if node.security_state == SecurityState.QUARANTINED)
    return quarantined / len(attacked)


def choose_strategy(state: WorldState, config: ExperimentConfig) -> str:
    if _detection_rate(state) >= config.adaptive_detection_threshold:
        return "stealthy"
    return "aggressive"


def step(state: WorldState, config: ExperimentConfig) -> tuple[WorldState, list[EventDraft]]:
    """Advance exactly one tick. Pure, synchronous, total."""
    strategy = choose_strategy(state, config)
    sources = sorted(
        node_id
        for node_id, node in state.nodes.items()
        if node.security_state == SecurityState.COMPROMISED
    )

    drafts: list[EventDraft] = []
    claims: dict[str, str] = {}

    for source in sources:
        source_node = state.nodes[source]
        healthy_neighbors = sorted(
            t
            for t in source_node.neighbors
            if state.nodes[t].security_state == SecurityState.HEALTHY
        )
        if not healthy_neighbors:
            continue

        degree = {t: len(state.nodes[t].neighbors) for t in healthy_neighbors}
        if strategy == "aggressive":
            target = sorted(healthy_neighbors, key=lambda t: (-degree[t], t))[0]
        else:
            target = sorted(healthy_neighbors, key=lambda t: (degree[t], t))[0]

        same = state.nodes[target].software_type == source_node.software_type
        p = config.p_same if same else config.p_cross
        draw = rng(config.seed, state.tick, target, f"adaptive:{source}").random()

        drafts.append(
            EventDraft(
                sim_tick=state.tick,
                event_type=EventType.COMPROMISE_ATTEMPTED,
                source_agent_id=source,
                target_agent_id=target,
                metadata={"probability": p, "strategy": strategy},
            )
        )

        if draw < p:
            already_claimed = target in claims
            metadata: dict[str, object] = {"probability": p, "strategy": strategy}
            if already_claimed:
                metadata["already_compromised"] = True
            else:
                claims[target] = source
            drafts.append(
                EventDraft(
                    sim_tick=state.tick,
                    event_type=EventType.COMPROMISE_SUCCEEDED,
                    source_agent_id=source,
                    target_agent_id=target,
                    metadata=metadata,
                )
            )
        else:
            drafts.append(
                EventDraft(
                    sim_tick=state.tick,
                    event_type=EventType.COMPROMISE_FAILED,
                    source_agent_id=source,
                    target_agent_id=target,
                    metadata={"probability": p, "strategy": strategy},
                )
            )

    new_nodes = dict(state.nodes)
    for target, source in claims.items():
        new_nodes[target] = replace(
            new_nodes[target],
            security_state=SecurityState.COMPROMISED,
            compromised_by=source,
            tick_compromised=state.tick,
        )

    new_state = WorldState(
        tick=state.tick + 1,
        nodes=new_nodes,
        edges=state.edges,
        compromised_graph_nodes=state.compromised_graph_nodes,
    )
    return new_state, drafts


class AdaptiveAttackerScenario:
    name = "adaptive_attacker"

    def step(
        self, state: WorldState, config: ExperimentConfig
    ) -> tuple[WorldState, list[EventDraft]]:
        return step(state, config)


adaptive_attacker_scenario = AdaptiveAttackerScenario()
