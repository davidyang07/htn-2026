"""HTTP contract for optional post-hoc incident explanation."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.runtime.registry import runtime_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    runtime_registry.clear()
    yield
    runtime_registry.clear()


def test_explanation_route_returns_safe_full_recovery_evidence(monkeypatch):
    monkeypatch.setattr(
        "app.runtime.explain.resolve_explanation_provider", lambda settings: None
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/runtime/sessions",
            json={
                "objective": "Fix the auth bug.",
                "workers": [
                    {"id": "security-researcher", "role": "Security Researcher"},
                    {"id": "developer", "role": "Developer"},
                    {"id": "reviewer", "role": "Reviewer"},
                ],
            },
        )
        assert created.status_code == 201
        session_id = created.json()["session_id"]

        client.post(
            f"/api/runtime/sessions/{session_id}/tasks/start",
            json={
                "worker_id": "security-researcher",
                "task": "Investigate the authentication vulnerability.",
            },
        )
        client.post(
            f"/api/runtime/sessions/{session_id}/artifacts",
            json={
                "id": "researcher-report",
                "worker_id": "security-researcher",
                "kind": "report",
                "summary": "This arbitrary report body must not enter evidence.",
            },
        )
        denied = client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={
                "worker_id": "security-researcher",
                "resource_path": "demo_target/secrets/demo_secret.txt",
            },
        )
        assert denied.json()["decision"] == "deny"

        client.post(
            f"/api/runtime/sessions/{session_id}/reassign",
            json={
                "from_worker_id": "security-researcher",
                "to_worker": {
                    "id": "replacement-researcher",
                    "role": "Replacement Researcher",
                },
                "task": "Continue from trusted context.",
                "context_artifact_ids": [],
            },
        )
        for passed, exit_code, summary in (
            (False, 1, "1 failed"),
            (True, 0, "8 passed"),
        ):
            client.post(
                f"/api/runtime/sessions/{session_id}/test-run",
                json={
                    "worker_id": "developer",
                    "command": "pytest demo_target",
                    "exit_code": exit_code,
                    "passed": passed,
                    "summary": summary,
                },
            )
        client.post(
            f"/api/runtime/sessions/{session_id}/tasks/complete",
            json={"worker_id": "reviewer", "step": "review", "detail": "Approved."},
        )
        client.post(
            f"/api/runtime/sessions/{session_id}/recover",
            json={"summary": "Recovered after independent review."},
        )

        before = client.get(f"/api/runtime/sessions/{session_id}").json()
        response = client.get(f"/api/runtime/sessions/{session_id}/explanation")
        after = client.get(f"/api/runtime/sessions/{session_id}").json()

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "deterministic"
    assert body["label"] == "Deterministic post-hoc explanation"
    assert "commentary only" in body["authority"]
    assert body["evidence"]["policy"]["rule"] == "protected_path"
    assert body["evidence"]["policy"]["outcome"] == "deny"
    assert body["evidence"]["quarantine"]["state"] == "quarantined"
    assert body["evidence"]["containment"] == {
        "tainted_artifact_ids": ["researcher-report"],
        "excluded_from_replacement_context": True,
    }
    assert body["evidence"]["replacement"]["replacement_worker_id"] == (
        "replacement-researcher"
    )
    assert body["evidence"]["before_fix_test"]["passed"] is False
    assert body["evidence"]["after_fix_test"]["passed"] is True
    assert body["evidence"]["reviewer"]["result"] == "Approved."
    assert body["evidence"]["final_recovery_state"] == "recovered"
    assert "arbitrary report body" not in response.text
    assert before == after
