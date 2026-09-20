"""Contract tests for the deliberately narrow explanation evidence."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.explanation.evidence import build_incident_evidence
from app.explanation.models import (
    ContainmentEvidence,
    IncidentEvidence,
    IncidentWorkerEvidence,
    PolicyEvidence,
    QuarantineEvidence,
)
from app.runtime.session import LiveRuntimeSession


def _evidence(**updates: object) -> IncidentEvidence:
    values: dict[str, object] = {
        "session_id": uuid4(),
        "worker": IncidentWorkerEvidence(
            worker_id="security-researcher",
            role="Security Researcher",
            assigned_task="Investigate the authentication bug.",
        ),
        "requested_resource_path": "demo_target/secrets/demo_secret.txt",
        "policy": PolicyEvidence(
            rule="protected_path",
            reason="The requested directory is protected.",
        ),
        "quarantine": QuarantineEvidence(worker_id="security-researcher"),
        "containment": ContainmentEvidence(
            tainted_artifact_ids=("researcher-report",),
            excluded_from_replacement_context=True,
        ),
        "final_recovery_state": "under_attack",
    }
    values.update(updates)
    return IncidentEvidence.model_validate(values)


def test_incident_evidence_has_an_explicit_safe_field_allowlist():
    assert set(IncidentEvidence.model_fields) == {
        "schema_version",
        "session_id",
        "worker",
        "requested_resource_path",
        "policy",
        "quarantine",
        "containment",
        "replacement",
        "before_fix_test",
        "after_fix_test",
        "reviewer",
        "final_recovery_state",
    }


@pytest.mark.parametrize(
    "unsafe_field",
    ["protected_file_contents", "api_key", "authorization", "prompt", "completion", "source"],
)
def test_incident_evidence_rejects_fields_that_could_carry_unsafe_payloads(
    unsafe_field: str,
):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _evidence(**{unsafe_field: "must-not-enter-evidence"})


def test_incident_evidence_is_immutable_after_validation():
    evidence = _evidence()

    with pytest.raises(ValidationError, match="Instance is frozen"):
        evidence.requested_resource_path = "changed"  # type: ignore[misc]


def test_builder_projects_the_complete_recovery_from_recorded_events_only():
    async def build() -> LiveRuntimeSession:
        session = LiveRuntimeSession("Fix the auth bug.")
        await session.register_worker("repo-analyst", "Repo Analyst")
        await session.register_worker("security-researcher", "Security Researcher")
        await session.register_worker("developer", "Developer")
        await session.register_worker("reviewer", "Reviewer")
        session.record_artifact("repo-map", "repo-analyst", "analysis", "Safe repository map.")
        await session.start_worker(
            "security-researcher", "Investigate the authentication vulnerability."
        )
        session.record_artifact(
            "researcher-report", "security-researcher", "report", "Untrusted report."
        )
        await session.request_resource(
            "security-researcher", "demo_target/secrets/demo_secret.txt"
        )
        await session.reassign(
            from_worker_id="security-researcher",
            to_worker_id="replacement-researcher",
            role="Replacement Researcher",
            task="Continue from trusted context.",
        )
        await session.record_test_run(
            "developer",
            passed=False,
            summary="1 failed",
            exit_code=1,
            command="pytest demo_target",
        )
        await session.record_test_run(
            "developer",
            passed=True,
            summary="8 passed",
            exit_code=0,
            command="pytest demo_target",
        )
        await session.complete_task(
            "reviewer", step_name="review", detail="Approved from test evidence."
        )
        await session.recover(summary="The recovered workflow completed.")
        return session

    import asyncio

    evidence = build_incident_evidence(asyncio.run(build()))

    assert evidence is not None
    assert evidence.worker.assigned_task == "Investigate the authentication vulnerability."
    assert evidence.requested_resource_path == "demo_target/secrets/demo_secret.txt"
    assert evidence.policy.rule == "protected_path"
    assert evidence.policy.outcome == "deny"
    assert evidence.quarantine.state == "quarantined"
    assert evidence.containment.tainted_artifact_ids == ("researcher-report",)
    assert evidence.containment.excluded_from_replacement_context is True
    assert evidence.replacement is not None
    assert evidence.replacement.replacement_worker_id == "replacement-researcher"
    assert evidence.before_fix_test is not None and evidence.before_fix_test.passed is False
    assert evidence.after_fix_test is not None and evidence.after_fix_test.passed is True
    assert evidence.reviewer is not None
    assert evidence.reviewer.result == "Approved from test evidence."
    assert evidence.final_recovery_state == "recovered"
