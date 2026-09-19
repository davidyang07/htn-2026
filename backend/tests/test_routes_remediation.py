from fastapi.testclient import TestClient

from app.main import app


def _start_experiment(client: TestClient, **overrides) -> dict:
    body = {
        "seed": 7,
        "node_count": 25,
        "max_ticks": 30,
        "defense_enabled": False,
        "p_same": 0.6,
        "p_cross": 0.6,
    }
    body.update(overrides)
    resp = client.post("/api/experiments", json=body)
    assert resp.status_code == 201
    return resp.json()


def _finish(client: TestClient, exp_id: str) -> None:
    import time

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if client.get(f"/api/experiments/{exp_id}").json()["status"] == "finished":
            return
        time.sleep(0.05)
    raise AssertionError("experiment did not finish in time")


def test_remediation_recommends_enabling_defense_when_it_is_off_and_spread_is_high():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        _finish(client, exp_id)

        resp = client.get(f"/api/experiments/{exp_id}/remediation")
        assert resp.status_code == 200
        recs = resp.json()["recommendations"]
        assert len(recs) == 1
        assert recs[0]["config_diff"] == {"defense_enabled": True}


def test_remediation_404_for_unknown_experiment():
    with TestClient(app) as client:
        resp = client.get(
            "/api/experiments/00000000-0000-0000-0000-000000000000/remediation"
        )
        assert resp.status_code == 404


def test_applying_the_recommendation_measurably_improves_compromise_fraction():
    # The re-test loop: take the recommendation's config_diff, start a NEW
    # experiment with it applied (same seed/topology), and confirm the
    # metric it targets actually improves -- proving the fix is not
    # fabricated (docs/PLAN.md §7).
    with TestClient(app) as client:
        baseline_id = _start_experiment(client)["experiment_id"]
        _finish(client, baseline_id)
        baseline_metrics = client.get(f"/api/experiments/{baseline_id}/metrics").json()
        recs = client.get(f"/api/experiments/{baseline_id}/remediation").json()["recommendations"]
        assert recs

        fixed_id = _start_experiment(client, **recs[0]["config_diff"])["experiment_id"]
        _finish(client, fixed_id)
        fixed_metrics = client.get(f"/api/experiments/{fixed_id}/metrics").json()

        assert fixed_metrics["compromise_fraction"] < baseline_metrics["compromise_fraction"]


def test_remediation_recommends_raising_sentinel_count_when_one_is_compromised():
    with TestClient(app) as client:
        exp_id = _start_experiment(
            client,
            sentinel_count=1,
            active_scenarios=["propagation", "sentinel_compromise"],
            sentinel_compromise_rate=1.0,
            defense_enabled=True,
            detector_sensitivity=1.0,
        )["experiment_id"]
        _finish(client, exp_id)

        graph_resp = client.get(f"/api/experiments/{exp_id}/graph").json()
        sentinels = [n for n in graph_resp["nodes"] if n["node_type"] == "sentinel"]
        assert any(n["security_state"] == "compromised" for n in sentinels)

        recs = client.get(f"/api/experiments/{exp_id}/remediation").json()["recommendations"]
        assert recs
        assert recs[0]["config_diff"] == {"sentinel_count": 2}
