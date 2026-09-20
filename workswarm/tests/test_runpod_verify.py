import httpx
import pytest

from workswarm.check_runpod import report_payload
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


def test_chat_probe_posts_openai_compatible_request():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "id": "cmpl-test",
                "choices": [{"message": {"role": "assistant", "content": "ready"}}],
            },
        )

    verifier = RunPodVerifier(_model(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = verifier.probe_chat(max_tokens=8)

    assert result.probe.ok is True
    assert result.response_chars == 5
    assert captured["path"] == "/v1/chat/completions"
    assert '"model":"Qwen/Qwen2.5-Coder-7B-Instruct"' in captured["body"]
    assert '"max_tokens":8' in captured["body"]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}),
    ],
)
def test_chat_probe_rejects_http_and_response_shape_failures(response):
    verifier = RunPodVerifier(
        _model(), client=httpx.Client(transport=httpx.MockTransport(lambda _: response))
    )
    result = verifier.probe_chat()
    assert result.probe.ok is False
    assert result.response_chars == 0


def test_full_verification_measures_first_and_warm_completions():
    chat_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chat_calls
        if request.url.path == "/health":
            return httpx.Response(200)
        if request.url.path == "/v1/models":
            return httpx.Response(
                200, json={"data": [{"id": "Qwen/Qwen2.5-Coder-7B-Instruct"}]}
            )
        if request.url.path == "/v1/chat/completions":
            chat_calls += 1
            return httpx.Response(
                200, json={"choices": [{"message": {"content": f"ready-{chat_calls}"}}]}
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    verifier = RunPodVerifier(_model(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    report = verifier.verify()

    assert report.ready is True
    assert report.first_completion is not None
    assert report.warm_completion is not None
    assert report.first_completion.probe.latency_ms >= 0
    assert report.warm_completion.probe.latency_ms >= 0
    assert chat_calls == 2


def test_full_verification_stops_after_failed_health():
    requested_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        return httpx.Response(503)

    verifier = RunPodVerifier(_model(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    report = verifier.verify()

    assert report.ready is False
    assert report.models is None
    assert report.first_completion is None
    assert report.warm_completion is None
    assert requested_paths == ["/health"]


def test_startup_measurement_polls_until_healthy():
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200 if attempts == 3 else 503)

    verifier = RunPodVerifier(_model(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = verifier.wait_for_health(max_wait_s=1, poll_interval_s=0, sleep_fn=lambda _: None)

    assert result.healthy is True
    assert result.attempts == 3
    assert result.cold_start_ms >= 0


def test_health_report_is_useful_but_never_contains_credentials_or_full_url():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        if request.url.path == "/v1/models":
            return httpx.Response(
                200, json={"data": [{"id": "Qwen/Qwen2.5-Coder-7B-Instruct"}]}
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ready"}}]}
        )

    model = _model()
    verifier = RunPodVerifier(model, client=httpx.Client(transport=httpx.MockTransport(handler)))
    payload = report_payload(model, verifier.verify())
    serialized = str(payload)

    assert payload["ready"] is True
    assert payload["endpoint_host"] == "pod.invalid"
    assert payload["first_completion"]["latency_ms"] >= 0
    assert payload["warm_completion"]["latency_ms"] >= 0
    assert "test-token" not in serialized
    assert "https://" not in serialized
