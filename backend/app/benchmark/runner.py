"""Headless benchmark execution (Priority 1): runs one ExperimentConfig to
completion with zero wall-clock pacing, zero EventBus, zero websocket --
just the deterministic engine plus (for presets that include an async
scenario like "prompt_injection") a MockProvider-backed gateway by default,
so the whole suite is a zero-real-provider-call, fully reproducible replay.
Reuses app/engine/simulate.py, app/scenarios/registry.py,
app/graph/builder.py, and app/metrics/compute.py verbatim -- no new
simulation logic.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from uuid import uuid4

from app.config import get_settings
from app.engine.propagation import is_finished
from app.engine.simulate import simulate
from app.engine.state import WorldState
from app.engine.tick import advance
from app.engine.topology import build_world
from app.events.emitter import EventEmitter
from app.gateway.factory import build_gateway, build_http_client
from app.graph.builder import build_security_graph
from app.graph.security_graph import SecurityGraph
from app.metrics import compute as metrics
from app.scenarios.registry import run_async_scenarios
from app.schemas.events import Event, EventDraft, EventType
from app.schemas.experiment import ExperimentConfig


@dataclass
class BenchmarkRun:
    name: str
    config: ExperimentConfig
    final_state: WorldState
    graph: SecurityGraph
    events: list[Event]
    metrics: dict[str, float | int | None]
    duration_s: float


def _uses_async_scenario(config: ExperimentConfig) -> bool:
    """Mirrors orchestrator/runner.py's own condition for calling
    run_async_scenarios at all: a gateway only exists (app/gateway/
    factory.py::build_gateway) when real_agent_count > 0, regardless of
    whether an async scenario name happens to be in active_scenarios (the
    default value includes "prompt_injection" unconditionally -- see
    ExperimentConfig -- so scenario-name membership alone is not a reliable
    signal)."""
    return config.real_agent_count > 0


def _compute_metrics(state: WorldState, graph: SecurityGraph, events: list[Event]) -> dict:
    return {
        "compromise_fraction": metrics.compromise_fraction(state),
        "retained_utility": metrics.retained_utility(state),
        "blast_radius_fraction": metrics.blast_radius_fraction(graph),
        "privileged_exposure": metrics.privileged_exposure(graph),
        "security_plane_integrity": metrics.security_plane_integrity(graph),
        "attack_success_rate": metrics.attack_success_rate(events),
        "false_quarantine_rate": metrics.false_quarantine_rate(events),
        "detection_latency": metrics.detection_latency(state, events),
        "containment_latency": metrics.containment_latency(events),
    }


def _drafts_to_events(drafts: list[EventDraft]) -> list[Event]:
    return EventEmitter(experiment_id=uuid4()).emit(drafts)


def run_headless(name: str, config: ExperimentConfig) -> BenchmarkRun:
    start = time.monotonic()
    state, drafts = simulate(config)
    events = _drafts_to_events(drafts)
    graph = build_security_graph(state, config)
    return BenchmarkRun(
        name=name,
        config=config,
        final_state=state,
        graph=graph,
        events=events,
        metrics=_compute_metrics(state, graph, events),
        duration_s=time.monotonic() - start,
    )


async def _run_headless_async(name: str, config: ExperimentConfig) -> BenchmarkRun:
    start = time.monotonic()
    async with build_http_client() as http_client:
        gateway = build_gateway(config, get_settings(), http_client)
        assert gateway is not None  # every async preset sets real_agent_count > 0

        drafts: list[EventDraft] = [
            EventDraft(sim_tick=0, event_type=EventType.EXPERIMENT_STARTED)
        ]
        state, topology_drafts = build_world(config)
        drafts.extend(topology_drafts)

        while not is_finished(state, config):
            state, tick_drafts = advance(state, config)
            state, async_drafts = await run_async_scenarios(
                state, config, gateway, tick=state.tick
            )
            drafts.extend([*tick_drafts, *async_drafts])

    events = _drafts_to_events(drafts)
    graph = build_security_graph(state, config)
    return BenchmarkRun(
        name=name,
        config=config,
        final_state=state,
        graph=graph,
        events=events,
        metrics=_compute_metrics(state, graph, events),
        duration_s=time.monotonic() - start,
    )


def run_headless_async(name: str, config: ExperimentConfig) -> BenchmarkRun:
    return asyncio.run(_run_headless_async(name, config))


def run_preset(name: str, config: ExperimentConfig) -> BenchmarkRun:
    if _uses_async_scenario(config):
        return run_headless_async(name, config)
    return run_headless(name, config)
