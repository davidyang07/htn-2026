"""Project an incident event log into the safe explanation evidence contract."""

from collections.abc import Iterable

from app.explanation.models import (
    ContainmentEvidence,
    IncidentEvidence,
    IncidentWorkerEvidence,
    PolicyEvidence,
    QuarantineEvidence,
    ReplacementEvidence,
    ReviewerEvidence,
    TestEvidence,
)
from app.runtime.session import LiveRuntimeSession
from app.schemas.events import Event, EventType


def _text(value: object, *, default: str = "unknown", limit: int = 2000) -> str:
    """Accept only scalar text and keep every evidence value bounded."""
    if not isinstance(value, str):
        return default
    value = value.strip()
    return value[:limit] if value else default


def _first(
    events: Iterable[Event], event_type: EventType, *, agent_id: str | None = None
) -> Event | None:
    return next(
        (
            event
            for event in events
            if event.event_type == event_type
            and (agent_id is None or event.agent_id == agent_id)
        ),
        None,
    )


def _test_evidence(event: Event) -> TestEvidence:
    return TestEvidence(
        passed=event.metadata.get("passed") is True,
        exit_code=(
            event.metadata["exit_code"]
            if isinstance(event.metadata.get("exit_code"), int)
            else None
        ),
        summary=_text(event.metadata.get("detail"), default="Test result recorded.", limit=1000),
    )


def build_incident_evidence(session: LiveRuntimeSession) -> IncidentEvidence | None:
    """Return safe evidence only after the deterministic deny cascade exists.

    The builder is a read-only projection.  It selects individual allowlisted
    fields; it never serializes an event, artifact, worker, prompt, completion,
    request body, or repository file wholesale.
    """
    events = session.bus.since(-1) or []
    violation = _first(events, EventType.POLICY_VIOLATION)
    if violation is None or violation.agent_id is None:
        return None

    worker_id = violation.agent_id
    quarantine = _first(events, EventType.AGENT_QUARANTINED, agent_id=worker_id)
    if quarantine is None:
        return None

    worker = session.workers.get(worker_id)
    assignments = [
        event
        for event in events
        if event.event_type == EventType.TASK_ASSIGNED and event.agent_id == worker_id
    ]
    assigned_task = (
        _text(
            assignments[-1].metadata.get("task"),
            default="Assigned task not recorded.",
            limit=1000,
        )
        if assignments
        else None
    )

    tainted_ids = tuple(
        _text(artifact_id, limit=64)
        for artifact_id in quarantine.metadata.get("tainted_artifacts", [])
        if isinstance(artifact_id, str)
    )

    reassignment = next(
        (
            event
            for event in events
            if event.event_type == EventType.TASK_REASSIGNED
            and event.source_agent_id == worker_id
            and event.target_agent_id
        ),
        None,
    )
    replacement = None
    excluded_from_context = None
    if reassignment is not None and reassignment.target_agent_id is not None:
        replacement_id = reassignment.target_agent_id
        created = _first(events, EventType.AGENT_CREATED, agent_id=replacement_id)
        replacement_worker = session.workers.get(replacement_id)
        trusted_context = (
            created.metadata.get("trusted_context", []) if created is not None else []
        )
        trusted_ids = {
            artifact_id for artifact_id in trusted_context if isinstance(artifact_id, str)
        }
        excluded_from_context = not any(
            artifact_id in trusted_ids for artifact_id in tainted_ids
        )
        replacement = ReplacementEvidence(
            quarantined_worker_id=worker_id,
            replacement_worker_id=replacement_id,
            replacement_role=(
                _text(created.metadata.get("role"), limit=64)
                if created is not None
                else _text(getattr(replacement_worker, "role", None), limit=64)
            ),
        )

    test_events = [
        event
        for event in events
        if event.event_type == EventType.TASK_COMPLETED
        and event.metadata.get("step") == "pytest"
    ]
    failed_tests = [event for event in test_events if event.metadata.get("passed") is False]
    passed_tests = [event for event in test_events if event.metadata.get("passed") is True]

    reviewer_event = next(
        (
            event
            for event in reversed(events)
            if event.event_type == EventType.TASK_COMPLETED
            and event.metadata.get("step") == "review"
            and event.agent_id
        ),
        None,
    )
    reviewer = (
        ReviewerEvidence(
            worker_id=reviewer_event.agent_id or "unknown",
            result=_text(
                reviewer_event.metadata.get("detail"),
                default="Review completed.",
                limit=1000,
            ),
        )
        if reviewer_event is not None
        else None
    )

    return IncidentEvidence(
        session_id=session.session_id,
        worker=IncidentWorkerEvidence(
            worker_id=worker_id,
            role=_text(getattr(worker, "role", None), limit=64),
            assigned_task=assigned_task,
        ),
        requested_resource_path=_text(
            violation.metadata.get("resource"), default="unknown resource", limit=2000
        ),
        policy=PolicyEvidence(
            rule=_text(violation.metadata.get("violation_type"), limit=64),
            reason=_text(violation.metadata.get("reason"), limit=1000),
        ),
        quarantine=QuarantineEvidence(worker_id=worker_id),
        containment=ContainmentEvidence(
            tainted_artifact_ids=tainted_ids,
            excluded_from_replacement_context=excluded_from_context,
        ),
        replacement=replacement,
        before_fix_test=_test_evidence(failed_tests[0]) if failed_tests else None,
        after_fix_test=_test_evidence(passed_tests[-1]) if passed_tests else None,
        reviewer=reviewer,
        final_recovery_state=session.workflow_state,
    )
