"""Attestation replay (docs/PLAN.md §5).

Deterministic, rule-based, composable (does NOT own the tick increment).
Only meaningful once an attestation_service SECURITY_CONTROL node exists
(sentinel_count > 0, per app/graph/builder.py::_attach_security_plane).

Nonces are the simulation tick itself: `state.tick` is already a monotonic
counter (docs/SPEC.md's fixed-tick engine), so a legitimate attestation's
nonce always equals the current tick -- no separate persisted
high-water-mark is needed to detect a stale one, matching the "verify by
exact matching, never an LLM judge" principle already established by Phase
2's confidential-token leak check. Each tick, every currently-COMPROMISED
agent attempts an attestation: with probability `attestation_replay_rate`
it presents a stale nonce (`max(0, tick - 1)`) instead of the fresh one --
ATTESTATION_VERIFIED's metadata.replayed flags exactly that case.

Defaults to a strict no-op (attestation_replay_rate == 0.0).
"""

from __future__ import annotations

from app.engine.rng import rng
from app.engine.state import SecurityState, WorldState
from app.graph.builder import build_security_graph
from app.graph.types import NodeType
from app.schemas.events import EventDraft, EventType
from app.schemas.experiment import ExperimentConfig


def step(state: WorldState, config: ExperimentConfig) -> tuple[WorldState, list[EventDraft]]:
    """Advance attestation issuance/verification for one tick. Pure,
    synchronous, total. Does not increment state.tick or mutate WorldState."""
    if config.attestation_replay_rate <= 0.0 or config.sentinel_count <= 0:
        return state, []

    graph = build_security_graph(state, config)
    controls = graph.nodes_of_type(NodeType.SECURITY_CONTROL)
    if not any(n.attrs.get("kind") == "attestation_service" for n in controls):
        return state, []

    compromised_agents = sorted(
        node_id
        for node_id, node in state.nodes.items()
        if node.security_state == SecurityState.COMPROMISED
    )

    drafts: list[EventDraft] = []
    for agent_id in compromised_agents:
        draw = rng(config.seed, state.tick, agent_id, "attestation_replay").random()
        replayed = draw < config.attestation_replay_rate
        nonce = max(0, state.tick - 1) if replayed else state.tick
        drafts.append(
            EventDraft(
                sim_tick=state.tick,
                event_type=EventType.ATTESTATION_ISSUED,
                agent_id=agent_id,
                metadata={"nonce": nonce},
            )
        )
        drafts.append(
            EventDraft(
                sim_tick=state.tick,
                event_type=EventType.ATTESTATION_VERIFIED,
                agent_id=agent_id,
                metadata={"nonce": nonce, "replayed": replayed},
            )
        )

    return state, drafts


class AttestationScenario:
    name = "attestation"

    def step(
        self, state: WorldState, config: ExperimentConfig
    ) -> tuple[WorldState, list[EventDraft]]:
        return step(state, config)


attestation_scenario = AttestationScenario()
