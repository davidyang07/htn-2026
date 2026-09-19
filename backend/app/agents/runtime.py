"""The Agent Runtime (docs/BRIEF.md §6, docs/PHASE_2_PLAN.md §2, §7): the one
place real-agent LLM interaction happens. Deliberately NOT part of
app/engine/ -- a real model call is irreducible async I/O, which
app/engine/propagation.py::step()'s purity contract forbids. Called by
ExperimentRunner, once per tick, only after the pure, synchronous
engine.tick.advance() has already run.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from app.agents.prompts import INJECTION_PAYLOAD, build_system_prompt, response_leaked_token
from app.engine.state import SecurityState, WorldState
from app.gateway.gateway import ModelGateway
from app.gateway.schemas import ModelRequest
from app.schemas.events import EventDraft, EventType
from app.schemas.experiment import ExperimentConfig


async def real_agent_step(
    state: WorldState, config: ExperimentConfig, gateway: ModelGateway, tick: int
) -> tuple[WorldState, list[EventDraft]]:
    """Advance real-real lateral-compromise attempts for one tick.

    Same (state, config) -> (state', drafts) shape as propagation.step(),
    but explicitly async and, with a real provider behind the gateway, not
    reproducible byte-for-byte -- only the deterministic mock-provider path
    is (docs/PHASE_2_PLAN.md §9). Never raises for a gateway/provider
    failure: ModelGateway.complete() already degrades that to `None`, which
    this function turns into a COMPROMISE_FAILED draft, same as a
    probabilistic miss.
    """
    sources = sorted(
        node_id
        for node_id, node in state.nodes.items()
        if node.agent_kind == "real" and node.security_state == SecurityState.COMPROMISED
    )

    # (source, target, probability, request) in deterministic sorted order --
    # this fixed order, not network completion order, is what keeps event
    # emission order deterministic under the mock provider (asyncio.gather
    # preserves input order in its results list regardless of completion
    # timing, so no manual reordering is needed after the gather below).
    attempts: list[tuple[str, str, float, ModelRequest]] = []
    for source in sources:
        source_node = state.nodes[source]
        targets = sorted(
            t
            for t in source_node.neighbors
            if state.nodes[t].agent_kind == "real"
            and state.nodes[t].security_state == SecurityState.HEALTHY
        )
        for target in targets:
            target_node = state.nodes[target]
            same = target_node.software_type == source_node.software_type
            probability = config.p_same if same else config.p_cross
            request = ModelRequest(
                agent_id=target,
                seed=config.seed,
                tick=tick,
                system_prompt=build_system_prompt(target_node),
                user_message=INJECTION_PAYLOAD,
                max_tokens=config.model_max_tokens,
                mock_leak_probability=probability,
                purpose="propagation",
            )
            attempts.append((source, target, probability, request))

    if not attempts:
        return state, []

    responses = await asyncio.gather(*(gateway.complete(a[3]) for a in attempts))

    drafts: list[EventDraft] = []
    claims: dict[str, str] = {}

    for (source, target, probability, _request), response in zip(
        attempts, responses, strict=True
    ):
        if response is None:
            drafts.append(
                EventDraft(
                    sim_tick=tick,
                    event_type=EventType.COMPROMISE_FAILED,
                    source_agent_id=source,
                    target_agent_id=target,
                    metadata={
                        "probability": probability,
                        "real_agent": True,
                        "gateway_error": True,
                    },
                )
            )
            continue

        drafts.append(
            EventDraft(
                sim_tick=tick,
                event_type=EventType.MODEL_REQUESTED,
                agent_id=target,
                metadata={"source_agent_id": source, "purpose": "propagation"},
            )
        )
        drafts.append(
            EventDraft(
                sim_tick=tick,
                event_type=EventType.MODEL_RESPONDED,
                agent_id=target,
                metadata={
                    "latency_ms": response.latency_ms,
                    "tokens_used": response.tokens_used,
                    "provider": response.provider,
                },
            )
        )

        target_node = state.nodes[target]
        assert target_node.confidential_token is not None
        leaked = response_leaked_token(response.text, target_node.confidential_token)

        drafts.append(
            EventDraft(
                sim_tick=tick,
                event_type=EventType.COMPROMISE_ATTEMPTED,
                source_agent_id=source,
                target_agent_id=target,
                metadata={"probability": probability, "real_agent": True},
            )
        )

        if not leaked:
            drafts.append(
                EventDraft(
                    sim_tick=tick,
                    event_type=EventType.COMPROMISE_FAILED,
                    source_agent_id=source,
                    target_agent_id=target,
                    metadata={"probability": probability, "real_agent": True},
                )
            )
            continue

        drafts.append(
            EventDraft(
                sim_tick=tick,
                event_type=EventType.TOOL_EXECUTED,
                agent_id=target,
                metadata={"tool_name": "reveal_confidential_token"},
            )
        )

        # Same claims/tie-break convention as propagation.step(): first
        # success in sorted source order wins the target; a later success on
        # an already-claimed target is recorded but does not re-win it.
        already_claimed = target in claims
        metadata: dict[str, object] = {"probability": probability, "real_agent": True}
        if already_claimed:
            metadata["already_compromised"] = True
        else:
            claims[target] = source
        drafts.append(
            EventDraft(
                sim_tick=tick,
                event_type=EventType.COMPROMISE_SUCCEEDED,
                source_agent_id=source,
                target_agent_id=target,
                metadata=metadata,
            )
        )

    if not claims:
        return state, drafts

    new_nodes = dict(state.nodes)
    for target, source in claims.items():
        new_nodes[target] = replace(
            new_nodes[target],
            security_state=SecurityState.COMPROMISED,
            compromised_by=source,
            tick_compromised=tick,
        )
    new_state = WorldState(tick=state.tick, nodes=new_nodes, edges=state.edges)
    return new_state, drafts
