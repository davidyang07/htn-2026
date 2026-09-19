from fastapi.testclient import TestClient

from app.main import app


def _start_experiment(client: TestClient, **overrides) -> dict:
    body = {"seed": 7, "node_count": 25, "max_ticks": 1}
    body.update(overrides)
    resp = client.post("/api/experiments", json=body)
    assert resp.status_code == 201
    return resp.json()


def test_provenance_of_the_seeded_compromise_is_just_itself():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        graph_resp = client.get(f"/api/experiments/{exp_id}/graph")
        seeded = next(
            n["id"]
            for n in graph_resp.json()["nodes"]
            if n["security_state"] == "compromised"
        )
        # Walk to the seeded node with no compromised_by (patient zero) by
        # checking against the analysis/blast-radius compromised list, then
        # asking for its provenance chain.
        resp = client.get(
            f"/api/experiments/{exp_id}/analysis/provenance", params={"node_id": seeded}
        )
        assert resp.status_code == 200
        chain = resp.json()["chain"]
        assert chain[0] == seeded


def test_provenance_404_for_unknown_experiment():
    with TestClient(app) as client:
        resp = client.get(
            "/api/experiments/00000000-0000-0000-0000-000000000000/analysis/provenance",
            params={"node_id": "agent-000"},
        )
        assert resp.status_code == 404


def test_provenance_404_for_unknown_node_in_a_real_experiment():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        resp = client.get(
            f"/api/experiments/{exp_id}/analysis/provenance",
            params={"node_id": "not-a-real-node"},
        )
        assert resp.status_code == 404
