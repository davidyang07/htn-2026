"""OpenTelemetry trace export (docs/PLAN.md priority 9) over a live
experiment's in-memory event buffer -- same registry.get(id) live-runner
pattern every other new endpoint in this codebase uses (routes_graph.py).
A history/replay equivalent can be added the same way later, once a
persisted-event-log path for it is needed."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.orchestrator.registry import registry
from app.telemetry.otel_export import build_otel_trace

router = APIRouter(prefix="/api/experiments", tags=["telemetry"])


@router.get("/{experiment_id}/otel-trace")
async def get_otel_trace(experiment_id: UUID) -> dict[str, Any]:
    runner = registry.get(experiment_id)
    if runner is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    # Bounded by EventBus.RING_SIZE, same limitation every other live-runner
    # event consumer already lives with (app/metrics/compute.py, docs/PLAN.md §6/§9).
    events = runner.bus.since(-1) or []
    return build_otel_trace(experiment_id, events)
