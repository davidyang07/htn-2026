"""Deterministic incident commentary, available without any provider."""

from app.explanation.models import (
    ExplanationSections,
    IncidentEvidence,
    IncidentExplanation,
    TestEvidence,
)

DETERMINISTIC_LABEL = "Deterministic post-hoc explanation"
SECURITY_AUTHORITY = (
    "The deterministic AgentShield policy and recorded runtime events made and prove "
    "the security decision; this explanation is commentary only."
)


def _test_result(result: TestEvidence | None, *, missing: str) -> str:
    if result is None:
        return missing
    outcome = "passed" if result.passed else "failed"
    exit_code = f" (exit code {result.exit_code})" if result.exit_code is not None else ""
    return f"{outcome}{exit_code}: {result.summary}"


def format_sections(sections: ExplanationSections) -> str:
    return "\n\n".join(
        (
            f"What happened? {sections.what_happened}",
            f"Why did AgentShield block it? {sections.why_blocked}",
            f"What was contained? {sections.what_was_contained}",
            f"How did the swarm recover? {sections.how_swarm_recovered}",
            f"What evidence proves recovery succeeded? {sections.recovery_evidence}",
        )
    )


def deterministic_explanation(evidence: IncidentEvidence | None) -> IncidentExplanation:
    """Explain recorded facts without I/O, inference, or state mutation."""
    if evidence is None:
        return IncidentExplanation(
            available=False,
            source="none",
            label=DETERMINISTIC_LABEL,
            authority=SECURITY_AUTHORITY,
            headline="No incident recorded yet.",
            body="AgentShield has not recorded a completed deterministic deny cascade.",
        )

    worker = evidence.worker
    task = worker.assigned_task or "an assigned task"
    sections = ExplanationSections(
        what_happened=(
            f"{worker.role} ({worker.worker_id}) was assigned “{task}” and requested "
            f"{evidence.requested_resource_path}. AgentShield denied the request and "
            "quarantined that worker."
        ),
        why_blocked=(
            f"The deterministic rule {evidence.policy.rule!r} returned "
            f"{evidence.policy.outcome!r}: {evidence.policy.reason}"
        ),
        what_was_contained=(
            f"The worker stayed quarantined. {len(evidence.containment.tainted_artifact_ids)} "
            "artifact(s) were marked untrusted"
            + (
                " and excluded from the replacement’s trusted context."
                if evidence.containment.excluded_from_replacement_context is True
                else "."
            )
        ),
        how_swarm_recovered=(
            (
                f"The swarm reassigned work from {evidence.replacement.quarantined_worker_id} "
                f"to {evidence.replacement.replacement_role} "
                f"({evidence.replacement.replacement_worker_id}) using trusted context only."
            )
            if evidence.replacement is not None
            else "Recovery has not yet created a replacement worker."
        ),
        recovery_evidence=(
            "Before-fix test: "
            f"{_test_result(evidence.before_fix_test, missing='not recorded')}. "
            "After-fix test: "
            f"{_test_result(evidence.after_fix_test, missing='not recorded')}. "
            f"Reviewer: {evidence.reviewer.result if evidence.reviewer else 'not recorded'}. "
            f"Final recovery state: {evidence.final_recovery_state}."
        ),
    )
    return IncidentExplanation(
        available=True,
        source="deterministic",
        label=DETERMINISTIC_LABEL,
        authority=SECURITY_AUTHORITY,
        headline="Protected resource request denied by deterministic policy.",
        body=format_sections(sections),
        sections=sections,
        evidence=evidence,
    )
