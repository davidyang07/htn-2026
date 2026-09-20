"""Ordering tests for the policy/read enforcement boundary."""

from collections.abc import Callable
from uuid import UUID

import pytest
from app.main import app
from app.runtime.registry import runtime_registry
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean_registry():
    runtime_registry.clear()
    yield
    runtime_registry.clear()


def _create_session(client: TestClient) -> str:
    response = client.post(
        "/api/runtime/sessions",
        json={
            "objective": "Exercise the enforcement boundary.",
            "workers": [{"id": "researcher", "role": "Security Researcher"}],
        },
    )
    assert response.status_code == 201
    return response.json()["session_id"]


def test_denied_request_never_invokes_the_resource_reader(monkeypatch) -> None:
    calls: list[str] = []

    def forbidden_read(path: str) -> str:
        calls.append(path)
        raise AssertionError("resource reader ran before a deny returned")

    monkeypatch.setattr("app.api.routes_runtime.read_sandbox_resource", forbidden_read)

    with TestClient(app) as client:
        session_id = _create_session(client)
        response = client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={
                "worker_id": "researcher",
                "resource_path": "demo_target/secrets/demo_secret.txt",
                "include_content": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["decision"] == "deny"
    assert response.json()["content"] is None
    assert calls == []


def test_allow_decision_and_event_are_recorded_before_the_reader_runs(monkeypatch) -> None:
    observed: list[tuple[str, str]] = []
    session_id = ""

    def observing_read(path: str) -> str:
        session = runtime_registry.get(UUID(session_id))
        assert session is not None
        events = session.bus.since(-1) or []
        observed.append((path, events[-1].event_type.value))
        return "safe fixture content"

    reader: Callable[[str], str] = observing_read
    monkeypatch.setattr("app.api.routes_runtime.read_sandbox_resource", reader)

    with TestClient(app) as client:
        session_id = _create_session(client)
        response = client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={
                "worker_id": "researcher",
                "resource_path": "demo_target/app/auth.py",
                "include_content": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["decision"] == "allow"
    assert response.json()["content"] == "safe fixture content"
    assert observed == [("demo_target/app/auth.py", "TOOL_EXECUTED")]
