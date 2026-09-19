"""Adapts app/engine/propagation.py::step to the Scenario interface
(docs/PLAN.md §3) without changing its behavior -- every existing test that
calls propagation.step directly keeps passing unmodified."""

from __future__ import annotations

from app.engine import propagation
from app.engine.state import WorldState
from app.schemas.events import EventDraft
from app.schemas.experiment import ExperimentConfig


class PropagationScenario:
    name = "propagation"

    def step(
        self, state: WorldState, config: ExperimentConfig
    ) -> tuple[WorldState, list[EventDraft]]:
        return propagation.step(state, config)


propagation_scenario = PropagationScenario()
