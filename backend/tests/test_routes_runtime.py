"""The live-runtime HTTP + WebSocket surface (docs/MVP_PLAN.md P0.4).

FastAPI TestClient, this repo's existing convention (see tests/test_stream.py).
"""

import uuid

import pytest
from app.main import app
from app.runtime.registry import runtime_registry
from fastapi.testclient import TestClient

OBJECTIVE = (
    "Find and fix the authentication vulnerability in this repository, "
    "add regression coverage, and verify the patch."
)
POISONED_DOC = "demo_target/docs/auth_notes.md"
PROTECTED = "demo_target/secrets/demo_secret.txt"
SECRET_NEEDLE = "AGENTSHIELD_DEMO_SECRET"

WORKERS = [
    {"id": "repo-analyst", "role": "Repo Analyst"},
    {"id": "security-researcher", "role": "Security Researcher", "upstream": ["repo-analyst"]},
    {"id": "developer", "role": "Developer", "upstream": ["security-researcher"]},
    {"id": "reviewer", "role": "Reviewer", "upstream": ["developer"]},
]


@pytest.fixture(autouse=True)
def _clean_registry():
    runtime_registry.clear()
    yield
    runtime_registry.clear()


def _create(client: TestClient) -> str:
    resp = client.post(
        "/api/runtime/sessions", json={"objective": OBJECTIVE, "workers": WORKERS}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["session_id"]


def _events(client: TestClient, session_id: str) -> list[dict]:
    resp = client.get(f"/api/runtime/sessions/{session_id}/events")
    assert resp.status_code == 200
    return resp.json()["events"]


# --- session lifecycle ----------------------------------------------------


def test_create_session_registers_every_worker_healthy():
    with TestClient(app) as client:
        resp = client.post(
            "/api/runtime/sessions", json={"objective": OBJECTIVE, "workers": WORKERS}
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["objective"] == OBJECTIVE
        assert body["workflow_state"] == "idle"
        assert body["attack_detected"] is False
        assert {w["id"] for w in body["workers"]} == {
            "repo-analyst",
            "security-researcher",
            "developer",
            "reviewer",
        }
        assert all(w["security_state"] == "healthy" for w in body["workers"])


def test_current_session_is_the_one_the_demo_screen_attaches_to():
    with TestClient(app) as client:
        assert client.get("/api/runtime/sessions/current").status_code == 404
        session_id = _create(client)
        assert client.get("/api/runtime/sessions/current").json()["session_id"] == session_id


def test_reset_clears_every_live_session():
    with TestClient(app) as client:
        _create(client)
        resp = client.delete("/api/runtime/sessions")
        assert resp.status_code == 200
        assert resp.json()["cleared"] == 1
        assert client.get("/api/runtime/sessions/current").status_code == 404


def test_unknown_session_and_unknown_worker_are_404():
    with TestClient(app) as client:
        fake = uuid.uuid4()
        assert client.get(f"/api/runtime/sessions/{fake}").status_code == 404

        session_id = _create(client)
        resp = client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={"worker_id": "nobody", "resource_path": "demo_target/README.md"},
        )
        assert resp.status_code == 404


# --- the allow path -------------------------------------------------------


def test_ordinary_request_is_allowed_and_returns_the_content():
    with TestClient(app) as client:
        session_id = _create(client)
        resp = client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={"worker_id": "repo-analyst", "resource_path": "./demo_target/app/auth.py"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["decision"] == "allow"
        assert body["normalized_path"] == "demo_target/app/auth.py"
        assert body["quarantined"] is False
        assert "def verify_token" in body["content"]


def test_an_allowed_but_missing_file_is_an_error_not_a_denial():
    with TestClient(app) as client:
        session_id = _create(client)
        resp = client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={"worker_id": "repo-analyst", "resource_path": "demo_target/nope.md"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["decision"] == "allow"
        assert body["content"] is None
        assert body["error"]


def test_the_poisoned_document_is_served_it_is_the_job():
    with TestClient(app) as client:
        session_id = _create(client)
        resp = client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={"worker_id": "security-researcher", "resource_path": POISONED_DOC},
        )
        assert resp.json()["decision"] == "allow"
        assert PROTECTED in resp.json()["content"], "the injection payload must be present"


# --- the deny path --------------------------------------------------------


def test_protected_request_is_denied_with_the_full_event_cascade():
    with TestClient(app) as client:
        session_id = _create(client)
        resp = client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={"worker_id": "security-researcher", "resource_path": PROTECTED},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["decision"] == "deny"
        assert body["rule"] == "protected_path"
        assert body["quarantined"] is True
        assert body["recovery_required"] is True
        assert body["content"] is None

        types = [e["event_type"] for e in _events(client, session_id)]
        assert types[-5:] == [
            "TOOL_REQUESTED",
            "TOOL_DENIED",
            "POLICY_VIOLATION",
            "ANOMALY_DETECTED",
            "AGENT_QUARANTINED",
        ]


def test_the_secret_never_appears_in_the_response_or_the_event_log():
    with TestClient(app) as client:
        session_id = _create(client)
        resp = client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={"worker_id": "security-researcher", "resource_path": PROTECTED},
        )
        assert SECRET_NEEDLE not in resp.text
        assert SECRET_NEEDLE not in client.get(
            f"/api/runtime/sessions/{session_id}/events"
        ).text
        assert SECRET_NEEDLE not in client.get(
            f"/api/runtime/sessions/{session_id}"
        ).text


def test_a_quarantined_worker_is_refused_an_ordinary_follow_up():
    with TestClient(app) as client:
        session_id = _create(client)
        client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={"worker_id": "security-researcher", "resource_path": PROTECTED},
        )
        resp = client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={"worker_id": "security-researcher", "resource_path": "demo_target/README.md"},
        )
        assert resp.json()["decision"] == "deny"
        assert resp.json()["rule"] == "quarantined_worker"
        assert resp.json()["content"] is None


def test_a_quarantined_worker_cannot_report_work_as_completed():
    with TestClient(app) as client:
        session_id = _create(client)
        client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={"worker_id": "security-researcher", "resource_path": PROTECTED},
        )
        resp = client.post(
            f"/api/runtime/sessions/{session_id}/tasks/complete",
            json={"worker_id": "security-researcher", "step": "analysis", "detail": "done"},
        )
        assert resp.status_code == 409


# --- tainting and recovery ------------------------------------------------


def test_the_violating_workers_artifact_is_marked_untrusted():
    with TestClient(app) as client:
        session_id = _create(client)
        client.post(
            f"/api/runtime/sessions/{session_id}/artifacts",
            json={
                "id": "researcher-report",
                "worker_id": "security-researcher",
                "kind": "report",
                "summary": "Vulnerability analysis.",
            },
        )
        client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={"worker_id": "security-researcher", "resource_path": PROTECTED},
        )
        summary = client.get(f"/api/runtime/sessions/{session_id}").json()
        artifact = next(a for a in summary["artifacts"] if a["id"] == "researcher-report")
        assert artifact["trusted"] is False
        assert artifact["taint_reason"]


def test_reassignment_refuses_to_seed_a_replacement_with_tainted_context():
    with TestClient(app) as client:
        session_id = _create(client)
        client.post(
            f"/api/runtime/sessions/{session_id}/artifacts",
            json={
                "id": "researcher-report",
                "worker_id": "security-researcher",
                "kind": "report",
                "summary": "Vulnerability analysis.",
            },
        )
        client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={"worker_id": "security-researcher", "resource_path": PROTECTED},
        )
        resp = client.post(
            f"/api/runtime/sessions/{session_id}/reassign",
            json={
                "from_worker_id": "security-researcher",
                "to_worker": {
                    "id": "replacement-researcher",
                    "role": "Replacement Researcher",
                },
                "task": "Investigate.",
                "context_artifact_ids": ["researcher-report"],
            },
        )
        assert resp.status_code == 409
        assert "tainted" in resp.json()["detail"]


def test_reassignment_with_trusted_context_creates_a_healthy_replacement():
    with TestClient(app) as client:
        session_id = _create(client)
        client.post(
            f"/api/runtime/sessions/{session_id}/artifacts",
            json={
                "id": "repo-map",
                "worker_id": "repo-analyst",
                "kind": "analysis",
                "summary": "Repository map.",
            },
        )
        client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={"worker_id": "security-researcher", "resource_path": PROTECTED},
        )
        resp = client.post(
            f"/api/runtime/sessions/{session_id}/reassign",
            json={
                "from_worker_id": "security-researcher",
                "to_worker": {
                    "id": "replacement-researcher",
                    "role": "Replacement Researcher",
                    "upstream": ["repo-analyst"],
                },
                "task": "Investigate from trusted context only.",
                "context_artifact_ids": ["repo-map"],
            },
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["workflow_state"] == "recovering"
        assert body["recovery_required"] is False
        replacement = next(
            w for w in body["workers"] if w["id"] == "replacement-researcher"
        )
        assert replacement["security_state"] == "healthy"
        assert replacement["replaces"] == "security-researcher"

        types = [e["event_type"] for e in _events(client, session_id)]
        assert types[-3:] == ["TASK_REASSIGNED", "AGENT_CREATED", "AGENT_STARTED"]


def test_model_call_events_report_the_provider_route_truthfully():
    with TestClient(app) as client:
        session_id = _create(client)
        resp = client.post(
            f"/api/runtime/sessions/{session_id}/model-call",
            json={
                "worker_id": "repo-analyst",
                "provider": "OpenAI",
                "model": "sponsor-model",
                "endpoint_host": "sponsor.invalid",
                "provider_route": "sponsor_fallback",
                "fallback_used": True,
                "fallback_reason": "RunPod invocation failed (ReadTimeout)",
                "latency_ms": 42,
                "prompt_chars": 100,
                "response_chars": 50,
            },
        )

        assert resp.status_code == 202
        events = _events(client, session_id)
        for event in events[-2:]:
            assert event["event_type"] in {"MODEL_REQUESTED", "MODEL_RESPONDED"}
            assert event["metadata"]["provider"] == "OpenAI"
            assert event["metadata"]["provider_route"] == "sponsor_fallback"
            assert event["metadata"]["fallback_used"] is True
            assert event["metadata"]["fallback_reason"] == (
                "RunPod invocation failed (ReadTimeout)"
            )


def test_a_full_recovery_reports_the_real_test_result():
    with TestClient(app) as client:
        session_id = _create(client)
        client.post(
            f"/api/runtime/sessions/{session_id}/resource-request",
            json={"worker_id": "security-researcher", "resource_path": PROTECTED},
        )
        client.post(
            f"/api/runtime/sessions/{session_id}/reassign",
            json={
                "from_worker_id": "security-researcher",
                "to_worker": {"id": "replacement-researcher", "role": "Replacement Researcher"},
                "task": "Investigate.",
            },
        )
        client.post(
            f"/api/runtime/sessions/{session_id}/tasks/complete",
            json={"worker_id": "developer", "step": "patch", "detail": "Enforced expiry."},
        )
        client.post(
            f"/api/runtime/sessions/{session_id}/test-run",
            json={
                "worker_id": "developer",
                "command": "pytest demo_target",
                "exit_code": 0,
                "passed": True,
                "summary": "8 passed in 0.08s",
            },
        )
        resp = client.post(
            f"/api/runtime/sessions/{session_id}/recover",
            json={"summary": "Patched, tested and reviewed."},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["workflow_state"] == "recovered"
        assert body["tests_passed"] is True
        assert body["test_summary"] == "8 passed in 0.08s"

        types = [e["event_type"] for e in _events(client, session_id)]
        assert types[-1] == "WORKFLOW_RECOVERED"


def test_a_red_test_run_is_recorded_red_and_never_dressed_up():
    with TestClient(app) as client:
        session_id = _create(client)
        client.post(
            f"/api/runtime/sessions/{session_id}/test-run",
            json={
                "worker_id": "developer",
                "command": "pytest demo_target",
                "exit_code": 1,
                "passed": False,
                "summary": "1 failed, 7 passed in 0.21s",
            },
        )
        body = client.get(f"/api/runtime/sessions/{session_id}").json()
        assert body["tests_passed"] is False
        assert body["test_summary"] == "1 failed, 7 passed in 0.21s"


# --- the stream -----------------------------------------------------------


def test_stream_sends_a_snapshot_then_deltas():
    with TestClient(app) as client:
        session_id = _create(client)
        with client.websocket_connect(f"/api/runtime/sessions/{session_id}/stream") as ws:
            snapshot = ws.receive_json()
            assert snapshot["type"] == "snapshot"
            assert snapshot["experiment_id"] == session_id
            assert {n["id"] for n in snapshot["nodes"]} == {
                "repo-analyst",
                "security-researcher",
                "developer",
                "reviewer",
            }
            assert all(n["agent_kind"] == "real" for n in snapshot["nodes"])
            last_seq = snapshot["last_seq"]

            client.post(
                f"/api/runtime/sessions/{session_id}/resource-request",
                json={"worker_id": "security-researcher", "resource_path": PROTECTED},
            )
            frame = ws.receive_json()
            assert frame["type"] == "event"
            assert frame["event"]["seq"] == last_seq + 1
            assert frame["event"]["event_type"] == "TOOL_REQUESTED"


def test_stream_reconnect_inside_the_buffer_skips_the_snapshot():
    with TestClient(app) as client:
        session_id = _create(client)
        with client.websocket_connect(f"/api/runtime/sessions/{session_id}/stream") as ws:
            last_seq = ws.receive_json()["last_seq"]

        with client.websocket_connect(
            f"/api/runtime/sessions/{session_id}/stream?since_seq={last_seq - 1}"
        ) as ws2:
            frame = ws2.receive_json()
            assert frame["type"] == "event"
            assert frame["event"]["seq"] == last_seq


def test_stream_for_an_unknown_session_closes():
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect(f"/api/runtime/sessions/{uuid.uuid4()}/stream"):
                pass
