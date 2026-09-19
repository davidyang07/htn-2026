from app.engine.state import WorldState
from app.scenarios.registry import run_sync_scenarios
from app.schemas.events import EventDraft
from app.schemas.experiment import ExperimentConfig
from app.security import detection


def advance(state: WorldState, config: ExperimentConfig) -> tuple[WorldState, list[EventDraft]]:
    """One full tick: active scenarios (docs/PLAN.md §3), then
    detection/quarantine. Pure, synchronous, total."""
    state, scenario_drafts = run_sync_scenarios(state, config)
    state, security_drafts = detection.step(state, config)
    return state, scenario_drafts + security_drafts
