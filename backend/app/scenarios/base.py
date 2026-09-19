"""Pluggable attack-scenario interface (docs/PLAN.md §3). `Scenario` is the
pure/synchronous shape app/engine/propagation.py::step already has;
`AsyncScenario` is the async/LLM-backed shape app/agents/runtime.py::
real_agent_step already has. Formalizing both as protocols lets new attacks
be added to app/scenarios/registry.py without touching the orchestrator's
tick loop -- neither existing function's body changes to satisfy these.
"""

from __future__ import annotations

from typing import Protocol

from app.engine.state import WorldState
from app.gateway.gateway import ModelGateway
from app.schemas.events import EventDraft
from app.schemas.experiment import ExperimentConfig


class Scenario(Protocol):
    name: str

    def step(
        self, state: WorldState, config: ExperimentConfig
    ) -> tuple[WorldState, list[EventDraft]]: ...


class AsyncScenario(Protocol):
    name: str

    async def step(
        self, state: WorldState, config: ExperimentConfig, gateway: ModelGateway, tick: int
    ) -> tuple[WorldState, list[EventDraft]]: ...
