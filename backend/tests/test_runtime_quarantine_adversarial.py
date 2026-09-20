"""Adversarial checks that quarantine removes every worker capability."""

import pytest
from app.main import app
from app.runtime.registry import runtime_registry
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean_registry():
    runtime_registry.clear()
    yield
    runtime_registry.clear()


def _quarantined_session(client: TestClient) -> str:
    created = client.post(
        "/api/runtime/sessions",
        json={
            "objective": "Verify quarantine.",
            "workers": [{"id": "researcher", "role": "Security Researcher"}],
        },
    )
    session_id = created.json()["session_id"]
    denied = client.post(
        f"/api/runtime/sessions/{session_id}/resource-request",
        json={
            "worker_id": "researcher",
            "resource_path": "demo_target/secrets/demo_secret.txt",
        },
    )
    assert denied.json()["quarantined"] is True
    return session_id


def test_quarantined_worker_cannot_use_any_worker_authored_endpoint() -> None:
    with TestClient(app) as client:
        session_id = _quarantined_session(client)
        attempts = [
            client.post(
                f"/api/runtime/sessions/{session_id}/tasks/start",
                json={"worker_id": "researcher", "task": "continue anyway"},
            ),
            client.post(
                f"/api/runtime/sessions/{session_id}/tasks/complete",
                json={"worker_id": "researcher", "step": "analysis", "detail": "done"},
            ),
            client.post(
                f"/api/runtime/sessions/{session_id}/model-call",
                json={
                    "worker_id": "researcher",
                    "provider": "synthetic",
                    "model": "test-model",
                    "endpoint_host": "example.test",
                    "latency_ms": 1,
                    "prompt_chars": 10,
                    "response_chars": 10,
                },
            ),
            client.post(
                f"/api/runtime/sessions/{session_id}/artifacts",
                json={
                    "id": "late-artifact",
                    "worker_id": "researcher",
                    "kind": "report",
                    "summary": "untrusted late output",
                },
            ),
            client.post(
                f"/api/runtime/sessions/{session_id}/test-run",
                json={
                    "worker_id": "researcher",
                    "command": "pytest synthetic",
                    "exit_code": 0,
                    "passed": True,
                    "summary": "1 passed",
                },
            ),
        ]

        assert [response.status_code for response in attempts] == [409, 409, 409, 409, 409]

        summary = client.get(f"/api/runtime/sessions/{session_id}").json()
        assert summary["model_calls"] == 0
        assert summary["artifacts"] == []
        assert summary["tests_passed"] is None
        assert summary["test_summary"] is None
