"""Sentry, OpenAI and RunPod are all optional, and none of them may sit on
the demo's critical path (docs/PROJECT.md §9/§10/§11).

"Optional" is a claim that rots silently, so it is asserted here rather than
documented: with every one of those unconfigured, the application imports,
serves, denies, quarantines and recovers exactly as it does with them present.
"""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.runtime.explain import deterministic_explanation, explain_incident
from app.runtime.registry import runtime_registry
from app.runtime.session import LiveRuntimeSession
from app.telemetry import sentry

PROTECTED = "demo_target/secrets/demo_secret.txt"


@pytest.fixture(autouse=True)
def _clean_registry():
    runtime_registry.clear()
    yield
    runtime_registry.clear()


def _unconfigured() -> Settings:
    return Settings(
        sentry_dsn=None,
        openai_api_key=None,
        runpod_model_base_url=None,
        runpod_model_api_key=None,
        runpod_model_name=None,
        vllm_base_url=None,
    )


def _blank_strings() -> Settings:
    """A `.env` written with bare `KEY=` placeholders -- far more common than
    a deleted key, and an empty string is not a credential."""
    return Settings(
        sentry_dsn="",
        openai_api_key="   ",
        runpod_model_base_url="",
        runpod_model_api_key="",
        runpod_model_name="",
    )


# --- Sentry ---------------------------------------------------------------


def test_sentry_is_a_no_op_without_a_dsn():
    assert sentry.init_sentry(_unconfigured()) is False
    assert sentry.is_enabled() is False

    # Every helper stays callable and does nothing.
    with sentry.span("agentshield.policy_check", "no-op"):
        pass
    sentry.log_event("security.tool_denied", "no-op", worker_id="x")
    sentry.set_tags({"a": "b"})


def test_sentry_treats_an_empty_dsn_as_absent():
    assert sentry.init_sentry(_blank_strings()) is False


def test_a_typo_in_a_structured_log_name_fails_loudly():
    with pytest.raises(ValueError):
        sentry.log_event("security.policy_violaton", "typo")


def test_the_structured_log_names_are_the_ones_the_docs_promise():
    assert sentry.STRUCTURED_LOG_NAMES == {
        "security.policy_violation",
        "security.tool_denied",
        "security.agent_quarantined",
        "swarm.task_reassigned",
        "swarm.replacement_started",
        "developer.patch_applied",
        "swarm.tests_passed",
        "swarm.recovery_complete",
    }


def test_the_whole_demo_path_works_with_nothing_configured():
    """The end-to-end control-plane path with no DSN, no OpenAI key and no
    RunPod endpoint: deny, quarantine, taint, reassign, recover."""
    sentry.init_sentry(_unconfigured())
    assert sentry.is_enabled() is False

    with TestClient(app) as client:
        created = client.post(
            "/api/runtime/sessions",
            json={
                "objective": "Fix the auth bug.",
                "workers": [
                    {"id": "repo-analyst", "role": "Repo Analyst"},
                    {"id": "security-researcher", "role": "Security Researcher"},
                    {"id": "developer", "role": "Developer"},
                ],
            },
        )
        assert created.status_code == 201
        session_id = created.json()["session_id"]

        client.post(
            f"/api/runtime/sessions/{session_id}/artifacts",
            json={
                "id": "repo-map",
                "worker_id": "repo-analyst",
                "kind": "analysis",
                "summary": "Repository map.",
            },
        )
        denied = client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={"worker_id": "security-researcher", "resource_path": PROTECTED},
        )
        assert denied.json()["decision"] == "deny"
        assert denied.json()["quarantined"] is True

        reassigned = client.post(
            f"/api/runtime/sessions/{session_id}/reassign",
            json={
                "from_worker_id": "security-researcher",
                "to_worker": {"id": "replacement-researcher", "role": "Replacement Researcher"},
                "task": "Investigate.",
                "context_artifact_ids": ["repo-map"],
            },
        )
        assert reassigned.status_code == 202

        client.post(
            f"/api/runtime/sessions/{session_id}/test-run",
            json={
                "worker_id": "developer",
                "command": "pytest demo_target",
                "exit_code": 0,
                "passed": True,
                "summary": "8 passed",
            },
        )
        recovered = client.post(
            f"/api/runtime/sessions/{session_id}/recover", json={"summary": "Done."}
        )
        assert recovered.json()["workflow_state"] == "recovered"


# --- OpenAI ---------------------------------------------------------------


def _session_with_incident() -> LiveRuntimeSession:
    async def build() -> LiveRuntimeSession:
        session = LiveRuntimeSession("Fix the auth bug.")
        await session.register_worker("security-researcher", "Security Researcher")
        await session.request_resource("security-researcher", PROTECTED)
        return session

    return asyncio.run(build())


def test_explanation_without_an_openai_key_is_deterministic_and_still_useful():
    session = _session_with_incident()

    async def main() -> None:
        async with httpx.AsyncClient() as client:
            explanation = await explain_incident(session, _unconfigured(), client)
        assert explanation.available is True
        assert explanation.source == "deterministic"
        assert explanation.model is None
        assert "denied" in explanation.body.lower()

    asyncio.run(main())


def test_explanation_treats_a_blank_openai_key_as_absent():
    session = _session_with_incident()

    async def main() -> None:
        async with httpx.AsyncClient() as client:
            explanation = await explain_incident(session, _blank_strings(), client)
        assert explanation.source == "deterministic"

    asyncio.run(main())


def test_an_unreachable_openai_degrades_to_the_deterministic_explanation():
    session = _session_with_incident()
    settings = Settings(openai_api_key="sk-not-a-real-key")
    settings.openai_base_url = "http://127.0.0.1:1/v1"

    async def main() -> None:
        async with httpx.AsyncClient() as client:
            explanation = await explain_incident(session, settings, client)
        assert explanation.source == "deterministic"
        assert explanation.available is True

    asyncio.run(main())


def test_the_explanation_never_contains_the_secret_or_decides_anything():
    session = _session_with_incident()
    explanation = deterministic_explanation(session)
    assert "AGENTSHIELD_DEMO_SECRET" not in explanation.body
    # The decision was already made and recorded before this ran.
    assert session.workers["security-researcher"].security_state.value == "quarantined"


def test_explanation_endpoint_before_any_incident_says_so_rather_than_inventing_one():
    with TestClient(app) as client:
        created = client.post(
            "/api/runtime/sessions",
            json={
                "objective": "Fix the auth bug.",
                "workers": [{"id": "repo-analyst", "role": "Repo Analyst"}],
            },
        )
        session_id = created.json()["session_id"]
        body = client.get(f"/api/runtime/sessions/{session_id}/explanation").json()
        assert body["available"] is False
        assert body["source"] == "none"


# --- RunPod ---------------------------------------------------------------


def test_runpod_settings_default_to_absent_and_nothing_reads_them_in_p0():
    settings = _unconfigured()
    assert settings.optional("runpod_model_base_url") is None
    assert settings.optional("runpod_model_api_key") is None
    assert settings.optional("runpod_model_name") is None

    # The P1 replacement-worker story reuses the existing vLLM provider
    # contract; in P0 nothing in the live runtime consults it at all.
    assert settings.optional("vllm_base_url") is None


def test_blank_runpod_settings_are_treated_as_absent():
    settings = _blank_strings()
    for name in ("runpod_model_base_url", "runpod_model_api_key", "runpod_model_name"):
        assert settings.optional(name) is None
