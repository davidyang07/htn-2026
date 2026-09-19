"""Adapts app/agents/runtime.py::real_agent_step to the AsyncScenario
interface (docs/PLAN.md §3) without changing its behavior."""

from __future__ import annotations

from app.agents.runtime import real_agent_step
from app.engine.state import WorldState
from app.gateway.gateway import ModelGateway
from app.schemas.events import EventDraft
from app.schemas.experiment import ExperimentConfig


class PromptInjectionScenario:
    name = "prompt_injection"

    async def step(
        self, state: WorldState, config: ExperimentConfig, gateway: ModelGateway, tick: int
    ) -> tuple[WorldState, list[EventDraft]]:
        return await real_agent_step(state, config, gateway, tick)


prompt_injection_scenario = PromptInjectionScenario()
