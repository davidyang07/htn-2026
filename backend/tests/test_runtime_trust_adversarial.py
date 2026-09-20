"""Adversarial checks for taint containment during replacement recovery."""

import pytest
from app.main import app
from app.runtime.registry import runtime_registry
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean_registry():
    runtime_registry.clear()
    yield
    runtime_registry.clear()


def _session_with_tainted_and_trusted_artifacts(client: TestClient) -> str:
    created = client.post(
        "/api/runtime/sessions",
        json={
            "objective": "Recover using trusted context only.",
            "workers": [
                {"id": "analyst", "role": "Repo Analyst"},
                {"id": "researcher", "role": "Security Researcher"},
            ],
        },
    )
    session_id = created.json()["session_id"]
    for artifact in (
        {
            "id": "trusted-map",
            "worker_id": "analyst",
            "kind": "analysis",
            "summary": "trusted repository map",
        },
        {
            "id": "tainted-report",
            "worker_id": "researcher",
            "kind": "report",
            "summary": "output produced before quarantine",
        },
    ):
        response = client.post(
            f"/api/runtime/sessions/{session_id}/artifacts", json=artifact
        )
        assert response.status_code == 201

    denied = client.post(
        f"/api/runtime/sessions/{session_id}/resource-request",
        json={
            "worker_id": "researcher",
            "resource_path": "demo_target/secrets/demo_secret.txt",
        },
    )
    assert denied.json()["quarantined"] is True
    return session_id


def _reassign(client: TestClient, session_id: str, artifact_ids: list[str]):
    return client.post(
        f"/api/runtime/sessions/{session_id}/reassign",
        json={
            "from_worker_id": "researcher",
            "to_worker": {
                "id": "replacement-researcher",
                "role": "Replacement Researcher",
            },
            "task": "Continue from trusted context.",
            "context_artifact_ids": artifact_ids,
        },
    )


def test_one_tainted_artifact_rejects_the_entire_reassignment_atomically() -> None:
    with TestClient(app) as client:
        session_id = _session_with_tainted_and_trusted_artifacts(client)
        before = client.get(f"/api/runtime/sessions/{session_id}").json()

        response = _reassign(
            client, session_id, ["trusted-map", "tainted-report"]
        )

        assert response.status_code == 409
        after = client.get(f"/api/runtime/sessions/{session_id}").json()
        assert after["step"] == before["step"]
        assert after["last_seq"] == before["last_seq"]
        assert after["recovery_required"] is True
        assert all(worker["id"] != "replacement-researcher" for worker in after["workers"])


def test_replacement_creation_event_contains_trusted_artifacts_only() -> None:
    with TestClient(app) as client:
        session_id = _session_with_tainted_and_trusted_artifacts(client)

        response = _reassign(client, session_id, ["trusted-map"])

        assert response.status_code == 202
        events = client.get(f"/api/runtime/sessions/{session_id}/events").json()["events"]
        created = next(
            event
            for event in reversed(events)
            if event["event_type"] == "AGENT_CREATED"
            and event["agent_id"] == "replacement-researcher"
        )
        assert created["metadata"]["trusted_context"] == ["trusted-map"]
        assert "tainted-report" not in created["metadata"]["trusted_context"]
