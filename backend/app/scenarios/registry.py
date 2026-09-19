"""Scenario registry (docs/PLAN.md §3): maps a scenario name to its
implementation and runs the active set each tick. Both `run_sync_scenarios`
and `run_async_scenarios` iterate `config.active_scenarios` in list order
(deterministic -- order is a config value, not iteration over a dict/set);
the default `["propagation", "prompt_injection"]` reproduces
engine/tick.py's and orchestrator/runner.py's pre-refactor behavior exactly
(each scenario already no-ops when it finds no eligible source/target
pair), so no existing test's expected output changes. Excluding
`"prompt_injection"` from an explicit `active_scenarios` list now genuinely
disables it -- previously impossible short of `real_agent_count=0`.
"""

from __future__ import annotations

import logging

from app.engine.state import WorldState
from app.gateway.gateway import ModelGateway
from app.scenarios.adaptive_attacker_scenario import adaptive_attacker_scenario
from app.scenarios.attestation_scenario import attestation_scenario
from app.scenarios.base import AsyncScenario, Scenario
from app.scenarios.byzantine_collusion_scenario import byzantine_collusion_scenario
from app.scenarios.prompt_injection_scenario import prompt_injection_scenario
from app.scenarios.propagation_scenario import propagation_scenario
from app.scenarios.sentinel_compromise_scenario import sentinel_compromise_scenario
from app.schemas.events import EventDraft
from app.schemas.experiment import ExperimentConfig

logger = logging.getLogger(__name__)

SYNC_SCENARIOS: dict[str, Scenario] = {
    propagation_scenario.name: propagation_scenario,
    adaptive_attacker_scenario.name: adaptive_attacker_scenario,
    sentinel_compromise_scenario.name: sentinel_compromise_scenario,
    attestation_scenario.name: attestation_scenario,
    byzantine_collusion_scenario.name: byzantine_collusion_scenario,
}

ASYNC_SCENARIOS: dict[str, AsyncScenario] = {
    prompt_injection_scenario.name: prompt_injection_scenario,
}


def _warn_if_truly_unknown(scenario_name: str) -> None:
    # A name valid in the *other* registry (e.g. "prompt_injection" seen by
    # run_sync_scenarios) is not a typo -- only warn when a name matches
    # neither registry.
    if scenario_name not in SYNC_SCENARIOS and scenario_name not in ASYNC_SCENARIOS:
        logger.warning("unknown scenario %r in active_scenarios; skipping", scenario_name)


def run_sync_scenarios(
    state: WorldState, config: ExperimentConfig
) -> tuple[WorldState, list[EventDraft]]:
    drafts: list[EventDraft] = []
    for scenario_name in config.active_scenarios:
        scenario = SYNC_SCENARIOS.get(scenario_name)
        if scenario is None:
            _warn_if_truly_unknown(scenario_name)
            continue
        state, scenario_drafts = scenario.step(state, config)
        drafts.extend(scenario_drafts)
    return state, drafts


async def run_async_scenarios(
    state: WorldState, config: ExperimentConfig, gateway: ModelGateway, tick: int
) -> tuple[WorldState, list[EventDraft]]:
    drafts: list[EventDraft] = []
    for scenario_name in config.active_scenarios:
        scenario = ASYNC_SCENARIOS.get(scenario_name)
        if scenario is None:
            _warn_if_truly_unknown(scenario_name)
            continue
        state, scenario_drafts = await scenario.step(state, config, gateway, tick)
        drafts.extend(scenario_drafts)
    return state, drafts
