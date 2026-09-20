"""Deterministic and provider-backed post-hoc commentary tests."""

from uuid import uuid4

from app.explanation.deterministic import deterministic_explanation
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


def _recovered_evidence() -> IncidentEvidence:
    return IncidentEvidence(
        session_id=uuid4(),
        worker=IncidentWorkerEvidence(
            worker_id="security-researcher",
            role="Security Researcher",
            assigned_task="Investigate the authentication vulnerability.",
        ),
        requested_resource_path="demo_target/secrets/demo_secret.txt",
        policy=PolicyEvidence(
            rule="protected_path",
            reason="demo_target/secrets/ is a protected directory; access is denied.",
        ),
        quarantine=QuarantineEvidence(worker_id="security-researcher"),
        containment=ContainmentEvidence(
            tainted_artifact_ids=("researcher-report",),
            excluded_from_replacement_context=True,
        ),
        replacement=ReplacementEvidence(
            quarantined_worker_id="security-researcher",
            replacement_worker_id="replacement-researcher",
            replacement_role="Replacement Researcher",
        ),
        before_fix_test=TestEvidence(passed=False, exit_code=1, summary="1 failed"),
        after_fix_test=TestEvidence(passed=True, exit_code=0, summary="8 passed"),
        reviewer=ReviewerEvidence(worker_id="reviewer", result="Approved."),
        final_recovery_state="recovered",
    )


def test_deterministic_explanation_answers_all_five_incident_questions():
    explanation = deterministic_explanation(_recovered_evidence())

    assert explanation.available is True
    assert explanation.source == "deterministic"
    assert explanation.label == "Deterministic post-hoc explanation"
    assert "commentary only" in explanation.authority
    assert explanation.evidence is not None
    assert explanation.sections is not None
    assert "protected_path" in explanation.sections.why_blocked
    assert "researcher-report" not in explanation.body
    assert "1 artifact(s)" in explanation.sections.what_was_contained
    assert "replacement-researcher" in explanation.sections.how_swarm_recovered
    assert "failed (exit code 1): 1 failed" in explanation.sections.recovery_evidence
    assert "passed (exit code 0): 8 passed" in explanation.sections.recovery_evidence
    assert "Reviewer: Approved." in explanation.sections.recovery_evidence
    assert "Final recovery state: recovered" in explanation.sections.recovery_evidence

    for question in (
        "What happened?",
        "Why did AgentShield block it?",
        "What was contained?",
        "How did the swarm recover?",
        "What evidence proves recovery succeeded?",
    ):
        assert question in explanation.body


def test_deterministic_explanation_does_not_invent_an_incident():
    explanation = deterministic_explanation(None)

    assert explanation.available is False
    assert explanation.source == "none"
    assert explanation.sections is None
    assert explanation.evidence is None
