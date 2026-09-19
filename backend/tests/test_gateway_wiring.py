import asyncio
import inspect
import uuid

from fastapi.testclient import TestClient

import app.benchmark.runner as benchmark_runner
from app.gateway.factory import build_http_client
from app.main import app
from app.schemas.experiment import ExperimentConfig


def test_vllm_without_base_url_returns_400():
    with TestClient(app) as client:
        resp = client.post(
            "/api/experiments",
            json={
                "seed": 1,
                "node_count": 25,
                "max_ticks": 1,
                "real_agent_count": 2,
                "model_provider": "vllm",
            },
        )
        assert resp.status_code == 400
        assert "vllm" in resp.json()["detail"].lower()


def test_mock_provider_with_real_agents_succeeds_regardless_of_vllm_config():
    with TestClient(app) as client:
        resp = client.post(
            "/api/experiments",
            json={
                "seed": 1,
                "node_count": 25,
                "max_ticks": 1,
                "real_agent_count": 2,
                "model_provider": "mock",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["config"]["real_agent_count"] == 2
        assert body["config"]["model_provider"] == "mock"
        client.post(f"/api/experiments/{body['experiment_id']}/stop")


def test_vllm_with_zero_real_agents_never_triggers_validation():
    """real_agent_count=0 means no real agent ever exists -- the vLLM
    base_url check only matters when real_agent_count > 0 (docs/PHASE_2_PLAN.md
    §8), so this must succeed even with model_provider="vllm" and nothing
    configured."""
    with TestClient(app) as client:
        resp = client.post(
            "/api/experiments",
            json={
                "seed": 1,
                "node_count": 25,
                "max_ticks": 1,
                "real_agent_count": 0,
                "model_provider": "vllm",
            },
        )
        assert resp.status_code == 201
        client.post(f"/api/experiments/{resp.json()['experiment_id']}/stop")


def test_default_config_has_zero_real_agents_and_mock_provider():
    with TestClient(app) as client:
        resp = client.post(
            "/api/experiments",
            json={"seed": uuid.uuid4().int % 1000, "node_count": 25, "max_ticks": 1},
        )
        assert resp.status_code == 201
        config = resp.json()["config"]
        assert config["real_agent_count"] == 0
        assert config["model_provider"] == "mock"
        client.post(f"/api/experiments/{resp.json()['experiment_id']}/stop")


# The highest per-call budget an experiment can legally ask for.
MAX_CONFIGURABLE_TIMEOUT_S = 120.0


def _assert_does_not_undercut_gateway_budget(timeout):
    assert timeout.read is None or timeout.read >= MAX_CONFIGURABLE_TIMEOUT_S
    assert timeout.write is None or timeout.write >= MAX_CONFIGURABLE_TIMEOUT_S
    # An unreachable host must still fail fast instead of hanging a tick.
    assert timeout.connect is not None and timeout.connect <= 30.0


def test_experiment_config_permits_the_timeout_ceiling_the_client_must_honor():
    config = ExperimentConfig(seed=1, model_timeout_s=MAX_CONFIGURABLE_TIMEOUT_S)
    assert config.model_timeout_s == MAX_CONFIGURABLE_TIMEOUT_S


def test_build_http_client_does_not_undercut_gateway_budget():
    """Regression: both call sites built httpx.AsyncClient() with no timeout,
    taking the 5s httpx default. That preempted the
    asyncio.wait_for(timeout=model_timeout_s) bound inside ModelGateway, so
    every model_timeout_s above 5 was dead config and a slow-but-healthy vLLM
    call was recorded as a ModelProviderError rather than being allowed its
    configured budget."""
    client = build_http_client()
    try:
        _assert_does_not_undercut_gateway_budget(client.timeout)
    finally:
        asyncio.run(client.aclose())


def test_app_lifespan_client_uses_the_shared_builder():
    with TestClient(app):
        _assert_does_not_undercut_gateway_budget(app.state.http_client.timeout)


def test_benchmark_runner_builds_its_client_through_the_shared_builder():
    """The runner is the path the golden demo and benchmark suite take; it
    kept the 5s default after the app was fixed, so assert it cannot drift
    again."""
    source = inspect.getsource(benchmark_runner._run_headless_async)
    assert "build_http_client()" in source
    assert "httpx.AsyncClient()" not in source
