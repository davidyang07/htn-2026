"""Deterministic and provider-backed post-hoc commentary tests."""

import asyncio
import json
from uuid import uuid4

import httpx

from app.explanation.deterministic import deterministic_explanation
from app.explanation.models import (
    ContainmentEvidence,
    IncidentEvidence,
    IncidentWorkerEvidence,
    PolicyEvidence,
    QuarantineEvidence,
    ReplacementEvidence,
    ReviewerEvidence,
    TestEvidence as IncidentTestEvidence,
)
from app.explanation.provider import ExplanationProvider
from app.explanation.service import explain_incident


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
        before_fix_test=IncidentTestEvidence(passed=False, exit_code=1, summary="1 failed"),
        after_fix_test=IncidentTestEvidence(passed=True, exit_code=0, summary="8 passed"),
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


def _provider() -> ExplanationProvider:
    return ExplanationProvider(
        provider="OpenRouter",
        model="sponsor/model",
        api_base="https://openrouter.example/api/v1",
        api_key="sponsor-secret",
        source="workswarm config.yaml",
    )


def _run_provider(
    handler: httpx.MockTransport,
    provider: ExplanationProvider | None = None,
):
    async def run():
        async with httpx.AsyncClient(transport=handler) as client:
            return await explain_incident(
                _recovered_evidence(),
                _provider() if provider is None else provider,
                client,
            )

    return asyncio.run(run())


def test_compatible_provider_generates_clearly_labeled_post_hoc_commentary():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://openrouter.example/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer sponsor-secret"
        payload = json.loads(request.content)
        evidence_payload = json.loads(payload["messages"][1]["content"])
        assert set(evidence_payload) == set(IncidentEvidence.model_fields)
        assert "prompt" not in evidence_payload
        assert "completion" not in evidence_payload
        sections = {
            "what_happened": "A protected resource was requested and denied.",
            "why_blocked": "The protected_path rule denied the request.",
            "what_was_contained": "The worker and its artifact were contained.",
            "how_swarm_recovered": "A clean replacement continued the task.",
            "recovery_evidence": "The red/green tests, review, and recovery event succeeded.",
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(sections)}}]},
        )

    explanation = _run_provider(httpx.MockTransport(handler))

    assert explanation.source == "openai"
    assert explanation.label == "AI-generated post-hoc explanation"
    assert "commentary only" in explanation.authority
    assert explanation.provider == "OpenRouter"
    assert explanation.model == "sponsor/model"
    assert explanation.sections is not None
    assert "clean replacement" in explanation.sections.how_swarm_recovered


def test_missing_provider_returns_deterministic_explanation_without_network_call():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request to {request.url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await explain_incident(_recovered_evidence(), None, client)

    explanation = asyncio.run(run())

    assert explanation.source == "deterministic"
    assert explanation.available is True


def test_provider_http_error_returns_deterministic_explanation():
    transport = httpx.MockTransport(lambda request: httpx.Response(503, request=request))

    explanation = _run_provider(transport)

    assert explanation.source == "deterministic"
    assert explanation.available is True


def test_provider_timeout_returns_deterministic_explanation():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    explanation = _run_provider(httpx.MockTransport(handler))

    assert explanation.source == "deterministic"


def test_malformed_provider_response_returns_deterministic_explanation():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "not json"}}]},
        )
    )

    explanation = _run_provider(transport)

    assert explanation.source == "deterministic"
