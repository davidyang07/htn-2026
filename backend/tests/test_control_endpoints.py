import time
import uuid

from fastapi.testclient import TestClient

from app.main import app


def _start_experiment(client: TestClient) -> dict:
    resp = client.post(
        "/api/experiments", json={"seed": 7, "node_count": 25, "max_ticks": 200}
    )
    assert resp.status_code == 201
    return resp.json()


def _start_experiment_that_finishes_fast(client: TestClient) -> dict:
    resp = client.post(
        "/api/experiments", json={"seed": 7, "node_count": 25, "max_ticks": 1}
    )
    assert resp.status_code == 201
    return resp.json()


def _wait_until_finished(client: TestClient, exp_id: str) -> None:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        resp = client.get(f"/api/experiments/{exp_id}")
        if resp.json()["status"] == "finished":
            return
        time.sleep(0.05)
    raise AssertionError("experiment did not finish in time")


def test_pause_happy_path_returns_200_with_paused_status():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        resp = client.post(f"/api/experiments/{exp_id}/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"


def test_resume_happy_path_returns_200_with_running_status():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        client.post(f"/api/experiments/{exp_id}/pause")
        resp = client.post(f"/api/experiments/{exp_id}/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"


def test_speed_happy_path_returns_200():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        resp = client.post(f"/api/experiments/{exp_id}/speed", json={"multiplier": 2.0})
        assert resp.status_code == 200


def test_pause_on_finished_experiment_returns_409_not_evicted():
    with TestClient(app) as client:
        exp_id = _start_experiment_that_finishes_fast(client)["experiment_id"]
        _wait_until_finished(client, exp_id)
        resp = client.post(f"/api/experiments/{exp_id}/pause")
        assert resp.status_code == 409


def test_speed_on_stopped_experiment_returns_404_because_evicted():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        client.post(f"/api/experiments/{exp_id}/stop")
        resp = client.post(f"/api/experiments/{exp_id}/speed", json={"multiplier": 2.0})
        assert resp.status_code == 404


def test_pause_unknown_id_returns_404():
    with TestClient(app) as client:
        resp = client.post(f"/api/experiments/{uuid.uuid4()}/pause")
        assert resp.status_code == 404


def test_resume_unknown_id_returns_404():
    with TestClient(app) as client:
        resp = client.post(f"/api/experiments/{uuid.uuid4()}/resume")
        assert resp.status_code == 404


def test_speed_unknown_id_returns_404():
    with TestClient(app) as client:
        resp = client.post(f"/api/experiments/{uuid.uuid4()}/speed", json={"multiplier": 2.0})
        assert resp.status_code == 404


def test_speed_out_of_range_multiplier_returns_422():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        resp = client.post(f"/api/experiments/{exp_id}/speed", json={"multiplier": 100.0})
        assert resp.status_code == 422


def test_stop_then_pause_returns_404_because_evicted():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        client.post(f"/api/experiments/{exp_id}/stop")
        resp = client.post(f"/api/experiments/{exp_id}/pause")
        assert resp.status_code == 404


def test_pause_twice_is_idempotent_both_200():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        first = client.post(f"/api/experiments/{exp_id}/pause")
        second = client.post(f"/api/experiments/{exp_id}/pause")
        assert first.status_code == 200
        assert second.status_code == 200


def test_stop_then_get_returns_404_registry_evicted_synchronously():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        stop_resp = client.post(f"/api/experiments/{exp_id}/stop")
        assert stop_resp.status_code == 200
        get_resp = client.get(f"/api/experiments/{exp_id}")
        assert get_resp.status_code == 404
