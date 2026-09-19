from fastapi.testclient import TestClient

from app.main import app


def _start_experiment(client: TestClient, **overrides) -> dict:
    body = {"seed": 7, "node_count": 25, "max_ticks": 1}
    body.update(overrides)
    resp = client.post("/api/experiments", json=body)
    assert resp.status_code == 201
    return resp.json()


def test_get_security_graph_returns_agent_nodes_and_edges():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        resp = client.get(f"/api/experiments/{exp_id}/graph")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["nodes"]) == 25
        assert all(n["node_type"] == "agent" for n in body["nodes"])
        assert body["edges"]


def test_get_security_graph_404_for_unknown_experiment():
    with TestClient(app) as client:
        resp = client.get(
            "/api/experiments/00000000-0000-0000-0000-000000000000/graph"
        )
        assert resp.status_code == 404


def test_attack_paths_endpoint_returns_paths_between_neighbors():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        graph_resp = client.get(f"/api/experiments/{exp_id}/graph")
        edges = graph_resp.json()["edges"]
        comm_edge = next(e for e in edges if e["edge_type"] == "communicates_with")

        resp = client.get(
            f"/api/experiments/{exp_id}/analysis/attack-paths",
            params={"source": comm_edge["source"], "target": comm_edge["target"]},
        )
        assert resp.status_code == 200
        paths = resp.json()["paths"]
        assert [comm_edge["source"], comm_edge["target"]] in paths


def test_blast_radius_endpoint_includes_every_compromised_node():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        resp = client.get(f"/api/experiments/{exp_id}/analysis/blast-radius")
        assert resp.status_code == 200
        body = resp.json()
        assert body["compromised"]
        assert set(body["compromised"]) <= set(body["reachable"])
        assert 0.0 < body["fraction"] <= 1.0


def test_critical_nodes_endpoint_returns_ranked_nodes():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        resp = client.get(f"/api/experiments/{exp_id}/analysis/critical-nodes", params={"top_n": 3})
        assert resp.status_code == 200
        nodes = resp.json()["nodes"]
        assert len(nodes) <= 3
        scores = [n["betweenness"] for n in nodes]
        assert scores == sorted(scores, reverse=True)
