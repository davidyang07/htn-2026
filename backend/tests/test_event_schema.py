import uuid

from app.engine.simulate import run_full
from app.events.emitter import EventEmitter
from app.schemas.events import M1_EVENT_TYPES
from app.schemas.experiment import ExperimentConfig


def test_event_schema_invariants():
    config = ExperimentConfig(seed=7, node_count=30, max_ticks=15)
    drafts = run_full(config)
    events = EventEmitter(experiment_id=uuid.uuid4()).emit(drafts)

    assert len(events) > 0
    assert all(e.schema_version == 1 for e in events)
    assert [e.seq for e in events] == list(range(len(events)))
    assert all(e.event_type in M1_EVENT_TYPES for e in events)
