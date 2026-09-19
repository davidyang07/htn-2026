from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.persistence.writer import PostgresWriter


class WriterRegistry:
    """Tracks UUID -> PostgresWriter, mirroring ExperimentRegistry's shape.

    Kept separate from ExperimentRegistry so persistence-specific state never
    leaks into the already-tested ExperimentRunner/ExperimentRegistry pair.
    """

    def __init__(self) -> None:
        self._writers: dict[UUID, PostgresWriter] = {}

    def add(self, experiment_id: UUID, writer: PostgresWriter) -> None:
        self._writers[experiment_id] = writer

    def get(self, experiment_id: UUID) -> PostgresWriter | None:
        return self._writers.get(experiment_id)

    def remove(self, experiment_id: UUID) -> None:
        self._writers.pop(experiment_id, None)

    async def shutdown_all(self) -> None:
        """Cancels every outstanding writer task and clears the registry.

        Called from app shutdown so a process exit (or, in tests, a
        TestClient lifespan exit) with experiments still live never leaves
        an orphaned drain-loop task pointing at a pool that's about to
        close.
        """
        writers = list(self._writers.values())
        self._writers.clear()
        for writer in writers:
            await writer.cancel()


writer_registry = WriterRegistry()
