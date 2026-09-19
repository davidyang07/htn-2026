from uuid import uuid4

from app.schemas.events import Event, EventType
from app.telemetry.otel_export import build_otel_trace


def _event(event_type: EventType, sim_tick: int, wall_time: str, **kwargs) -> Event:
    return Event(
        sim_tick=sim_tick,
        event_type=event_type,
        event_id=uuid4(),
        seq=sim_tick,
        experiment_id=uuid4(),
        wall_time=wall_time,
        **kwargs,
    )


def _root_span(trace: dict) -> dict:
    return trace["resourceSpans"][0]["scopeSpans"][0]["spans"][0]


def test_empty_events_yields_a_valid_zero_duration_trace():
    experiment_id = uuid4()
    trace = build_otel_trace(experiment_id, [])

    span = _root_span(trace)
    assert span["traceId"] == experiment_id.hex
    assert span["startTimeUnixNano"] == "0"
    assert span["endTimeUnixNano"] == "0"
    assert span["events"] == []
    assert {"key": "agentnet.event_count", "value": {"intValue": "0"}} in span["attributes"]


def test_trace_id_is_the_experiment_id_hex():
    experiment_id = uuid4()
    trace = build_otel_trace(experiment_id, [])
    assert _root_span(trace)["traceId"] == experiment_id.hex
    assert len(_root_span(trace)["traceId"]) == 32


def test_span_id_is_deterministic_for_the_same_experiment_id():
    experiment_id = uuid4()
    trace_a = build_otel_trace(experiment_id, [])
    trace_b = build_otel_trace(experiment_id, [])
    assert _root_span(trace_a)["spanId"] == _root_span(trace_b)["spanId"]
    assert len(_root_span(trace_a)["spanId"]) == 16


def test_different_experiment_ids_get_different_span_ids():
    trace_a = build_otel_trace(uuid4(), [])
    trace_b = build_otel_trace(uuid4(), [])
    assert _root_span(trace_a)["spanId"] != _root_span(trace_b)["spanId"]


def test_resource_attributes_include_service_name_and_experiment_id():
    experiment_id = uuid4()
    trace = build_otel_trace(experiment_id, [])
    attrs = trace["resourceSpans"][0]["resource"]["attributes"]
    assert {"key": "service.name", "value": {"stringValue": "agentnet"}} in attrs
    assert {
        "key": "agentnet.experiment_id",
        "value": {"stringValue": str(experiment_id)},
    } in attrs


def test_events_become_span_events_in_order_with_the_right_name():
    experiment_id = uuid4()
    events = [
        _event(EventType.EXPERIMENT_STARTED, 0, "2026-01-01T00:00:00Z"),
        _event(
            EventType.COMPROMISE_SUCCEEDED,
            3,
            "2026-01-01T00:00:03Z",
            source_agent_id="agent-000",
            target_agent_id="agent-001",
        ),
    ]
    trace = build_otel_trace(experiment_id, events)
    span_events = _root_span(trace)["events"]

    assert len(span_events) == 2
    assert span_events[0]["name"] == "EXPERIMENT_STARTED"
    assert span_events[1]["name"] == "COMPROMISE_SUCCEEDED"


def test_span_time_bounds_span_the_full_event_window():
    experiment_id = uuid4()
    events = [
        _event(EventType.EXPERIMENT_STARTED, 0, "2026-01-01T00:00:00Z"),
        _event(EventType.EXPERIMENT_STOPPED, 5, "2026-01-01T00:00:05Z"),
    ]
    trace = build_otel_trace(experiment_id, events)
    span = _root_span(trace)

    start_s = int(span["startTimeUnixNano"]) / 1_000_000_000
    end_s = int(span["endTimeUnixNano"]) / 1_000_000_000
    assert end_s - start_s == 5.0


def test_agent_source_target_and_metadata_become_span_event_attributes():
    experiment_id = uuid4()
    events = [
        _event(
            EventType.COMPROMISE_SUCCEEDED,
            1,
            "2026-01-01T00:00:01Z",
            source_agent_id="agent-000",
            target_agent_id="agent-001",
            metadata={"probability": 0.5, "strategy": "aggressive"},
        )
    ]
    trace = build_otel_trace(experiment_id, events)
    attrs = {a["key"]: a["value"] for a in _root_span(trace)["events"][0]["attributes"]}

    assert attrs["agentnet.sim_tick"] == {"intValue": "1"}
    assert attrs["agentnet.source_agent_id"] == {"stringValue": "agent-000"}
    assert attrs["agentnet.target_agent_id"] == {"stringValue": "agent-001"}
    assert attrs["agentnet.metadata.probability"] == {"doubleValue": 0.5}
    assert attrs["agentnet.metadata.strategy"] == {"stringValue": "aggressive"}


def test_agent_id_only_events_do_not_get_source_or_target_attributes():
    experiment_id = uuid4()
    events = [_event(EventType.ANOMALY_DETECTED, 2, "2026-01-01T00:00:02Z", agent_id="agent-000")]
    trace = build_otel_trace(experiment_id, events)
    keys = {a["key"] for a in _root_span(trace)["events"][0]["attributes"]}

    assert "agentnet.agent_id" in keys
    assert "agentnet.source_agent_id" not in keys
    assert "agentnet.target_agent_id" not in keys


def test_bool_metadata_maps_to_bool_value_not_int():
    experiment_id = uuid4()
    events = [
        _event(
            EventType.AGENT_QUARANTINED,
            1,
            "2026-01-01T00:00:01Z",
            agent_id="agent-000",
            metadata={"legitimate": False},
        )
    ]
    trace = build_otel_trace(experiment_id, events)
    attrs = {a["key"]: a["value"] for a in _root_span(trace)["events"][0]["attributes"]}
    assert attrs["agentnet.metadata.legitimate"] == {"boolValue": False}
