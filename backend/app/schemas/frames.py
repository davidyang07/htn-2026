from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.events import Event
from app.schemas.experiment import EdgeView, NodeView


class SnapshotFrame(BaseModel):
    type: Literal["snapshot"] = "snapshot"
    experiment_id: UUID
    last_seq: int
    sim_tick: int
    status: Literal["running", "paused", "finished", "stopped"]
    nodes: list[NodeView]
    edges: list[EdgeView]


class EventFrame(BaseModel):
    type: Literal["event"] = "event"
    event: Event


StreamFrame = Annotated[SnapshotFrame | EventFrame, Field(discriminator="type")]
