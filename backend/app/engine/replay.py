"""Reconstructs a persisted experiment's final WorldState by re-running the
deterministic engine from (seed, config) up to a target tick, rather than
reading the event log back. World state is already a pure function of
(seed, config) (docs/PLAN.md §2.3), and `experiments.final_sim_tick` is
already persisted (app/persistence/writer.py) -- so bounding the loop by
that tick, instead of always running to natural completion like
app/engine/simulate.py::simulate does, reconstructs the exact historical
final state whether the run finished naturally or was stopped early.
Mirrors app/orchestrator/runner.py's own per-tick loop (advance(), then
run_async_scenarios() when a gateway exists) so live and replayed state
can never diverge in how a tick is computed.

A real model provider (model_provider != "mock") is deliberately refused:
replaying it would either silently re-issue real network calls or (with no
reachable endpoint) fail outright, and a real LLM's output is not
guaranteed reproducible even with the same seed -- unlike MockProvider,
which this codebase already relies on for all deterministic replay/
benchmark work.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import httpx

from app.config import get_settings
from app.engine.propagation import is_finished
from app.engine.state import WorldState
from app.engine.tick import advance
from app.engine.topology import build_world
from app.events.emitter import EventEmitter
from app.gateway.factory import build_gateway
from app.scenarios.registry import run_async_scenarios
from app.schemas.events import Event, EventDraft, EventType
from app.schemas.experiment import ExperimentConfig


class ReplayUnsupportedError(Exception):
    """Raised when a persisted experiment's config cannot be safely replayed."""


def _uses_async_scenario(config: ExperimentConfig) -> bool:
    return config.real_agent_count > 0


def _should_continue(state: WorldState, config: ExperimentConfig, target_tick: int) -> bool:
    if state.tick >= target_tick:
        return False
    return not is_finished(state, config)


def _reconstruct_sync(
    config: ExperimentConfig, target_tick: int
) -> tuple[WorldState, list[EventDraft]]:
    drafts: list[EventDraft] = [EventDraft(sim_tick=0, event_type=EventType.EXPERIMENT_STARTED)]
    world, topology_drafts = build_world(config)
    drafts.extend(topology_drafts)
    while _should_continue(world, config, target_tick):
        world, tick_drafts = advance(world, config)
        drafts.extend(tick_drafts)
    return world, drafts


async def _reconstruct_async(
    config: ExperimentConfig, target_tick: int
) -> tuple[WorldState, list[EventDraft]]:
    async with httpx.AsyncClient() as http_client:
        gateway = build_gateway(config, get_settings(), http_client)
        assert gateway is not None  # real_agent_count > 0 is this function's only caller path

        drafts: list[EventDraft] = [
            EventDraft(sim_tick=0, event_type=EventType.EXPERIMENT_STARTED)
        ]
        state, topology_drafts = build_world(config)
        drafts.extend(topology_drafts)
        while _should_continue(state, config, target_tick):
            state, tick_drafts = advance(state, config)
            state, async_drafts = await run_async_scenarios(
                state, config, gateway, tick=state.tick
            )
            drafts.extend([*tick_drafts, *async_drafts])
    return state, drafts


def reconstruct_final_state(
    config: ExperimentConfig, target_tick: int
) -> tuple[WorldState, list[Event]]:
    if config.real_agent_count > 0 and config.model_provider != "mock":
        raise ReplayUnsupportedError(
            "replay reconstruction only supports model_provider='mock' -- a real "
            "provider run is not deterministically reproducible and replay must "
            "never silently re-issue real API calls"
        )

    if _uses_async_scenario(config):
        world, drafts = asyncio.run(_reconstruct_async(config, target_tick))
    else:
        world, drafts = _reconstruct_sync(config, target_tick)

    events = EventEmitter(experiment_id=uuid4()).emit(drafts)
    return world, events
