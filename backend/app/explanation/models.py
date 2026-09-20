"""Narrow, immutable contracts for post-hoc incident explanation."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EvidenceModel(BaseModel):
    """An immutable allowlist: unknown evidence fields are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class IncidentWorkerEvidence(EvidenceModel):
    worker_id: str
    role: str
    assigned_task: str | None = None


class PolicyEvidence(EvidenceModel):
    rule: str
    outcome: Literal["deny"] = "deny"
    reason: str


class QuarantineEvidence(EvidenceModel):
    worker_id: str
    state: Literal["quarantined"] = "quarantined"


class ContainmentEvidence(EvidenceModel):
    tainted_artifact_ids: tuple[str, ...] = ()
    excluded_from_replacement_context: bool


class ReplacementEvidence(EvidenceModel):
    quarantined_worker_id: str
    replacement_worker_id: str
    replacement_role: str


class TestEvidence(EvidenceModel):
    passed: bool
    exit_code: int | None = None
    summary: str


class ReviewerEvidence(EvidenceModel):
    worker_id: str
    result: str


class IncidentEvidence(EvidenceModel):
    """Safe facts copied from the recorded event stream, never raw payloads."""

    schema_version: Literal["1"] = "1"
    session_id: UUID
    worker: IncidentWorkerEvidence
    requested_resource_path: str
    policy: PolicyEvidence
    quarantine: QuarantineEvidence
    containment: ContainmentEvidence
    replacement: ReplacementEvidence | None = None
    before_fix_test: TestEvidence | None = None
    after_fix_test: TestEvidence | None = None
    reviewer: ReviewerEvidence | None = None
    final_recovery_state: Literal[
        "under_attack", "recovering", "recovered", "failed"
    ]


class ExplanationSections(EvidenceModel):
    what_happened: str
    why_blocked: str
    what_was_contained: str
    how_swarm_recovered: str
    recovery_evidence: str


class IncidentExplanation(EvidenceModel):
    """Commentary whose authority is explicitly separate from the verdict."""

    available: bool
    source: Literal["openai", "deterministic", "none"]
    label: str
    authority: str
    headline: str
    body: str
    sections: ExplanationSections | None = None
    evidence: IncidentEvidence | None = None
    provider: str | None = None
    model: str | None = None
