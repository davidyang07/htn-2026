import uuid

from fastapi.testclient import TestClient

from app.main import app


def _start_experiment(client: TestClient) -> dict:
    resp = client.post(
        "/api/experiments", json={"seed": 7, "node_count": 25, "max_ticks": 5}
    )
    assert resp.status_code == 201
    return resp.json()


def test_fresh_client_gets_snapshot_then_events():
    with TestClient(app) as client:
        summary = _start_experiment(client)
        exp_id = summary["experiment_id"]
        with client.websocket_connect(f"/api/experiments/{exp_id}/stream") as ws:
            first = ws.receive_json()
            assert first["type"] == "snapshot"
            assert first["experiment_id"] == exp_id
            last_seq = first["last_seq"]
            assert last_seq >= 0

            second = ws.receive_json()
            assert second["type"] == "event"
            assert second["event"]["seq"] == last_seq + 1


def test_reconnect_inside_buffer_skips_snapshot():
    with TestClient(app) as client:
        summary = _start_experiment(client)
        exp_id = summary["experiment_id"]
        with client.websocket_connect(f"/api/experiments/{exp_id}/stream") as ws:
            first = ws.receive_json()
            last_seq = first["last_seq"]

        with client.websocket_connect(
            f"/api/experiments/{exp_id}/stream?since_seq={last_seq - 1}"
        ) as ws2:
            frame = ws2.receive_json()
            assert frame["type"] == "event"
            assert frame["event"]["seq"] == last_seq


def test_reconnect_outside_buffer_gets_fresh_snapshot():
    with TestClient(app) as client:
        summary = _start_experiment(client)
        exp_id = summary["experiment_id"]
        with client.websocket_connect(
            f"/api/experiments/{exp_id}/stream?since_seq=-1000"
        ) as ws:
            frame = ws.receive_json()
            assert frame["type"] == "snapshot"


def test_unknown_experiment_id_closes_connection():
    with TestClient(app) as client:
        fake_id = uuid.uuid4()
        try:
            with client.websocket_connect(f"/api/experiments/{fake_id}/stream"):
                pass
            raised = False
        except Exception:
            raised = True
        assert raised
