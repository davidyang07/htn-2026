from uuid import UUID

from app.orchestrator.runner import ExperimentRunner


class ExperimentRegistry:
    """In-memory experiment registry — a dict (BRIEF §5)."""

    def __init__(self) -> None:
        self._runners: dict[UUID, ExperimentRunner] = {}

    def add(self, runner: ExperimentRunner) -> None:
        self._runners[runner.experiment_id] = runner

    def get(self, experiment_id: UUID) -> ExperimentRunner | None:
        return self._runners.get(experiment_id)

    def remove(self, experiment_id: UUID) -> None:
        self._runners.pop(experiment_id, None)


registry = ExperimentRegistry()
