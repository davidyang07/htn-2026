import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from app.schemas.events import Event, EventDraft


class EventEmitter:
    """Sole assigner of seq. One instance per experiment."""

    def __init__(self, experiment_id: uuid.UUID) -> None:
        self._experiment_id = experiment_id
        self._next_seq = 0

    @property
    def last_seq(self) -> int:
        return self._next_seq - 1

    def emit(self, drafts: Sequence[EventDraft]) -> list[Event]:
        events: list[Event] = []
        for draft in drafts:
            events.append(
                Event(
                    **draft.model_dump(),
                    event_id=uuid.uuid4(),
                    seq=self._next_seq,
                    experiment_id=self._experiment_id,
                    wall_time=datetime.now(UTC),
                )
            )
            self._next_seq += 1
        return events
