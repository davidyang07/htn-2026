"""Read-models over Postgres -- kept separate from schemas/experiment.py,
which is the live runner's contract, since these describe persisted rows,
not in-memory runner state."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.events import Event
from app.schemas.experiment import ExperimentConfig


class ExperimentListItem(BaseModel):
    experiment_id: UUID
    seed: int
    config: ExperimentConfig
    created_at: datetime
    final_status: Literal["finished", "stopped"] | None
    final_sim_tick: int | None
    final_last_seq: int | None
    # NULL until finalization runs or attempts to run; True only when a
    # gapless seq range [0, final_last_seq] was proven at finalize time.
    # False means the run finished/stopped but a batch failed somewhere
    # mid-run -- never inferred from final_status alone.
    is_complete: bool | None


class ExperimentListResponse(BaseModel):
    items: list[ExperimentListItem]
    next_cursor: str | None


class ExperimentDetail(ExperimentListItem):
    app_version: str
    schema_version: int
    completed_at: datetime | None


class EventHistoryResponse(BaseModel):
    events: list[Event]
    next_seq: int | None
