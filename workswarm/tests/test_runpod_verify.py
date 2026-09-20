import httpx
import pytest

from workswarm.config import ModelConfig
from workswarm.runpod_verify import RunPodVerifier, endpoint_urls


def _model() -> ModelConfig:
    return ModelConfig(
        provider="OpenAI",
        model_name="Qwen/Qwen2.5-Coder-7B-Instruct",
        api_key="test-token",
        api_base="https://pod.invalid/v1",
        source="RUNPOD_MODEL_*",
    )


@pytest.mark.parametrize(
    ("configured", "root"),
    [
        ("https://pod-8000.proxy.runpod.net", "https://pod-8000.proxy.runpod.net"),
        ("https://pod-8000.proxy.runpod.net/", "https://pod-8000.proxy.runpod.net"),
        ("https://pod-8000.proxy.runpod.net/v1", "https://pod-8000.proxy.runpod.net"),
        ("https://example.invalid/pod/v1/", "https://example.invalid/pod"),
    ],
)
def test_endpoint_urls_accept_service_root_or_openai_base(configured, root):
    urls = endpoint_urls(configured)

    assert urls.service_root == root
    assert urls.openai_base == f"{root}/v1"
    assert urls.health == f"{root}/health"
    assert urls.models == f"{root}/v1/models"
    assert urls.chat_completions == f"{root}/v1/chat/completions"


@pytest.mark.parametrize(
    "unsafe",
    [
        "pod-8000.proxy.runpod.net",
        "ftp://pod.invalid/v1",
        "https://token@pod.invalid/v1",
        "https://pod.invalid/v1?api_key=secret",
        "https://pod.invalid/v1#secret",
    ],
)
def test_endpoint_urls_refuse_ambiguous_or_credential_bearing_urls(unsafe):
    with pytest.raises(ValueError):
        endpoint_urls(unsafe)


@pytest.mark.parametrize(("status", "ok"), [(200, True), (401, False), (503, False)])
def test_health_probe_requires_http_200(status, ok):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(status)

    verifier = RunPodVerifier(_model(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = verifier.probe_health()

    assert result.ok is ok
    assert result.status_code == status
    assert result.latency_ms >= 0


def test_health_probe_reports_connection_failure_without_credentials():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("test-token must never escape", request=request)

    verifier = RunPodVerifier(_model(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = verifier.probe_health()

    assert result.ok is False
    assert result.status_code is None
    assert result.detail == "request failed (ConnectError)"
    assert "test-token" not in repr(result)


def test_models_probe_requires_the_configured_model():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "Qwen/Qwen2.5-Coder-7B-Instruct", "object": "model"},
                    {"id": "another-model", "object": "model"},
                ],
            },
        )

    verifier = RunPodVerifier(_model(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = verifier.probe_models()

    assert result.probe.ok is True
    assert result.expected_model_found is True
    assert result.model_ids == ("Qwen/Qwen2.5-Coder-7B-Instruct", "another-model")


def test_models_probe_rejects_wrong_or_malformed_catalog():
    responses = [
        httpx.Response(200, json={"data": [{"id": "wrong-model"}]}),
        httpx.Response(200, json={"unexpected": []}),
        httpx.Response(503),
    ]
    for response in responses:
        verifier = RunPodVerifier(
            _model(),
            client=httpx.Client(transport=httpx.MockTransport(lambda _: response)),
        )
        result = verifier.probe_models()
        assert result.probe.ok is False
        assert result.expected_model_found is False
