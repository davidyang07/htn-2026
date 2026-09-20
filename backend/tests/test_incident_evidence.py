"""Contract tests for the deliberately narrow explanation evidence."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.explanation.models import (
    ContainmentEvidence,
    IncidentEvidence,
    IncidentWorkerEvidence,
    PolicyEvidence,
    QuarantineEvidence,
)


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
