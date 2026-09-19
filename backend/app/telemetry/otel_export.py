"""OpenTelemetry-compatible trace export (docs/PLAN.md priority 9).

Scoped narrowly per docs/PLAN.md §9's own ruling on this priority --
"telemetry export, not orchestration" -- to avoid the ambiguity of a
LangGraph/MCP integration (what would either even mean concretely without
more product direction) and to stay clear of docs/BRIEF.md's explicit "not
a generic agent framework, don't compete with LangGraph." This exports
AgentShield's existing event log as an OTLP/JSON trace
(https://opentelemetry.io/docs/specs/otlp/#json-protobuf-encoding) so any
OTLP-compatible observability backend (Jaeger, Tempo, Honeycomb, ...) can
ingest an experiment's causal history for external analysis.

No new dependency: OTLP/JSON is a stable, documented wire format, built
here by hand rather than pulling in the opentelemetry-sdk package -- there
is no SDK-specific behavior (sampling, batching, live push export) this
needs, per CLAUDE.md's smallest-dependency-set preference.

One root span per experiment (covering its full recorded event window),
with every AgentShield Event mapped to an OTel *span event* -- a native
OpenTelemetry concept for a discrete, timestamped occurrence within a span
-- rather than inventing a per-event child span, which would misrepresent
events as having duration they don't have.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.schemas.events import Event

SERVICE_NAME = "agentnet"


def _attr(key: str, value: object) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _root_span_id(experiment_id: UUID) -> str:
    """Deterministic 64-bit span id (16 hex chars) derived from the
    experiment id -- exported traces are reproducible from the same
    experiment, matching this codebase's derived-keyed-determinism
    convention (app/engine/rng.py) even though OTel itself has no
    determinism requirement."""
    return hashlib.sha256(experiment_id.bytes + b"agentnet-root-span").hexdigest()[:16]


def _event_attributes(event: Event) -> list[dict[str, Any]]:
    attrs = [
        _attr("agentnet.sim_tick", event.sim_tick),
        _attr("agentnet.event_type", event.event_type.value),
    ]
    if event.agent_id is not None:
        attrs.append(_attr("agentnet.agent_id", event.agent_id))
    if event.source_agent_id is not None:
        attrs.append(_attr("agentnet.source_agent_id", event.source_agent_id))
    if event.target_agent_id is not None:
        attrs.append(_attr("agentnet.target_agent_id", event.target_agent_id))
    for key, value in event.metadata.items():
        attrs.append(_attr(f"agentnet.metadata.{key}", value))
    return attrs


def build_otel_trace(experiment_id: UUID, events: Sequence[Event]) -> dict[str, Any]:
    """Pure function: an OTLP/JSON ResourceSpans payload for one experiment's
    event log. Empty `events` still produces a valid, zero-duration trace
    rather than raising -- an experiment with no recorded events yet is a
    normal state (e.g. queried immediately after creation)."""
    trace_id = experiment_id.hex
    span_id = _root_span_id(experiment_id)

    timestamps_ns = [int(e.wall_time.timestamp() * 1_000_000_000) for e in events]
    start_ns = min(timestamps_ns) if timestamps_ns else 0
    end_ns = max(timestamps_ns) if timestamps_ns else start_ns

    span_events = [
        {
            "timeUnixNano": str(ts),
            "name": event.event_type.value,
            "attributes": _event_attributes(event),
        }
        for event, ts in zip(events, timestamps_ns, strict=True)
    ]

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        _attr("service.name", SERVICE_NAME),
                        _attr("agentnet.experiment_id", str(experiment_id)),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": SERVICE_NAME, "version": "1"},
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "name": "experiment",
                                "kind": 1,
                                "startTimeUnixNano": str(start_ns),
                                "endTimeUnixNano": str(end_ns),
                                "attributes": [_attr("agentnet.event_count", len(events))],
                                "events": span_events,
                            }
                        ],
                    }
                ],
            }
        ]
    }
