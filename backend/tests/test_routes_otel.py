from fastapi.testclient import TestClient

from app.main import app


def _start_experiment(client: TestClient, **overrides) -> dict:
    body = {"seed": 7, "node_count": 25, "max_ticks": 1}
    body.update(overrides)
    resp = client.post("/api/experiments", json=body)
    assert resp.status_code == 201
    return resp.json()


def test_otel_trace_endpoint_returns_a_valid_resource_spans_shape():
    with TestClient(app) as client:
        exp_id = _start_experiment(client)["experiment_id"]
        resp = client.get(f"/api/experiments/{exp_id}/otel-trace")
        assert resp.status_code == 200

        body = resp.json()
        span = body["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        assert span["traceId"] == exp_id.replace("-", "")
        assert len(span["events"]) > 0
        assert any(e["name"] == "EXPERIMENT_STARTED" for e in span["events"])

        resource_attrs = {
            a["key"]: a["value"] for a in body["resourceSpans"][0]["resource"]["attributes"]
        }
        assert resource_attrs["service.name"] == {"stringValue": "agentnet"}
        assert resource_attrs["agentnet.experiment_id"] == {"stringValue": exp_id}


def test_otel_trace_404_for_unknown_experiment():
    with TestClient(app) as client:
        resp = client.get(
            "/api/experiments/00000000-0000-0000-0000-000000000000/otel-trace"
        )
        assert resp.status_code == 404
