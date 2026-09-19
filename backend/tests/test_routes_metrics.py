from fastapi.testclient import TestClient

from app.main import app


def _start_experiment(client: TestClient, **overrides) -> dict:
    body = {"seed": 7, "node_count": 25, "max_ticks": 1}
    body.update(overrides)
    resp = client.post("/api/experiments", json=body)
    assert resp.status_code == 201
    return resp.json()


def test_metrics_endpoint_returns_all_fields_with_sane_bounds():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        resp = client.get(f"/api/experiments/{exp_id}/metrics")
        assert resp.status_code == 200
        body = resp.json()

        for key in (
            "compromise_fraction",
            "retained_utility",
            "blast_radius_fraction",
            "security_plane_integrity",
            "attack_success_rate",
            "false_quarantine_rate",
        ):
            assert 0.0 <= body[key] <= 1.0, key
        assert body["privileged_exposure"] >= 0
        assert body["compromise_fraction"] > 0.0
        for key in ("detection_latency", "containment_latency"):
            assert key in body
            assert body[key] is None or body[key] >= 0.0


def test_metrics_endpoint_404_for_unknown_experiment():
    with TestClient(app) as client:
        resp = client.get(
            "/api/experiments/00000000-0000-0000-0000-000000000000/metrics"
        )
        assert resp.status_code == 404
