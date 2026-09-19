from app.engine.propagation import is_finished
from app.engine.state import WorldState
from app.engine.tick import advance
from app.engine.topology import build_world
from app.schemas.events import EventDraft, EventType
from app.schemas.experiment import ExperimentConfig


def simulate(config: ExperimentConfig) -> tuple[WorldState, list[EventDraft]]:
    """Batch-run one full deterministic experiment, synchronously, returning
    the final WorldState alongside the full draft log.

    No asyncio, no bus, no wall-clock pacing, no async scenarios (those need
    a gateway -- see app/benchmark/runner.py::run_headless_async for the
    async-scenario equivalent used by benchmark presets that include
    "prompt_injection"). ExperimentRunner drives the same build_world/step/
    is_finished calls one tick at a time for live streaming instead.
    """
    drafts: list[EventDraft] = [
        EventDraft(sim_tick=0, event_type=EventType.EXPERIMENT_STARTED)
    ]
    world, topology_drafts = build_world(config)
    drafts.extend(topology_drafts)

    while not is_finished(world, config):
        world, tick_drafts = advance(world, config)
        drafts.extend(tick_drafts)

    return world, drafts


def run_full(config: ExperimentConfig) -> list[EventDraft]:
    """Used by tests and scripts/verify_determinism.py."""
    _, drafts = simulate(config)
    return drafts
