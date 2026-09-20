import asyncio

import httpx

import workswarm.config as model_config
from workswarm.config import NO_MODEL, ModelConfig, resolve_model, resolve_runpod_model
from workswarm.replacement_provider import (
    ReplacementFailover,
    provider_use_from_selection,
    select_replacement_provider,
    select_verified_replacement,
)
from workswarm.runpod_verify import RunPodVerifier


def _model(source: str, base_url: str) -> ModelConfig:
    return ModelConfig(
        provider="OpenAI",
        model_name=f"{source}-model",
        api_key="test-only",
        api_base=base_url,
        source=source,
    )


def test_healthy_runpod_is_selected_for_the_replacement():
    sponsor = _model("sponsor", "https://sponsor.invalid/v1")
    runpod = _model("runpod", "https://runpod.invalid/v1")

    selected = select_replacement_provider(
        sponsor=sponsor, runpod=runpod, runpod_healthy=True
    )

    assert selected.model is runpod
    assert selected.route == "runpod"
    assert selected.fallback_used is False


def test_missing_runpod_preserves_the_sponsor_backed_p0_route():
    sponsor = _model("sponsor", "https://sponsor.invalid/v1")

    selected = select_replacement_provider(
        sponsor=sponsor, runpod=None, runpod_healthy=False
    )

    assert selected.model is sponsor
    assert selected.route == "sponsor_fallback"
    assert selected.fallback_used is True
    actual_use = provider_use_from_selection(selected)
    assert actual_use.model is sponsor
    assert actual_use.route == "sponsor_fallback"
    assert actual_use.fallback_used is True


def test_no_provider_preserves_the_deterministic_p0_route():
    selected = select_replacement_provider(
        sponsor=NO_MODEL, runpod=None, runpod_healthy=False
    )

    assert selected.model is NO_MODEL
    assert selected.route == "deterministic_fallback"
    assert selected.fallback_used is True


def test_runpod_configuration_is_replacement_only(monkeypatch):
    monkeypatch.setattr(model_config, "workswarm_default_model", lambda: None)
    monkeypatch.setenv("AGENTSHIELD_MODEL_BASE_URL", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("RUNPOD_MODEL_BASE_URL", "https://runpod.invalid/v1")
    monkeypatch.setenv("RUNPOD_MODEL_NAME", "Qwen/Qwen2.5-Coder-7B-Instruct")

    assert resolve_model() is NO_MODEL
    runpod = resolve_runpod_model()
    assert runpod is not None
    assert runpod.api_base == "https://runpod.invalid/v1"
    assert runpod.model_name == "Qwen/Qwen2.5-Coder-7B-Instruct"
    assert runpod.source == "RUNPOD_MODEL_*"


def test_connection_failure_falls_back_to_sponsor_without_raising():
    sponsor = _model("sponsor", "https://sponsor.invalid/v1")
    runpod = _model("runpod", "https://runpod.invalid/v1")

    def factory(model):
        def unavailable(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route", request=request)

        return RunPodVerifier(
            model, client=httpx.Client(transport=httpx.MockTransport(unavailable))
        )

    resolved = select_verified_replacement(
        sponsor=sponsor, runpod=runpod, verifier_factory=factory
    )

    assert resolved.selection.model is sponsor
    assert resolved.selection.route == "sponsor_fallback"
    assert resolved.selection.fallback_used is True
    assert "ConnectError" in resolved.selection.reason
    assert resolved.verification is not None
    assert resolved.verification.ready is False


def test_timeout_falls_back_without_claiming_runpod():
    sponsor = _model("sponsor", "https://sponsor.invalid/v1")
    runpod = _model("runpod", "https://runpod.invalid/v1")

    def factory(model):
        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        return RunPodVerifier(
            model, client=httpx.Client(transport=httpx.MockTransport(timeout))
        )

    resolved = select_verified_replacement(
        sponsor=sponsor, runpod=runpod, verifier_factory=factory
    )

    assert resolved.selection.route == "sponsor_fallback"
    assert resolved.selection.model.source == "sponsor"
    assert "RunPod health check failed" in resolved.selection.reason
    assert "ReadTimeout" in resolved.selection.reason


def test_wrong_model_catalog_falls_back_to_sponsor():
    sponsor = _model("sponsor", "https://sponsor.invalid/v1")
    runpod = _model("runpod", "https://runpod.invalid/v1")

    def factory(model):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200)
            if request.url.path == "/v1/models":
                return httpx.Response(200, json={"data": [{"id": "wrong-model"}]})
            raise AssertionError("chat must not run for a mismatched model catalog")

        return RunPodVerifier(
            model, client=httpx.Client(transport=httpx.MockTransport(handler))
        )

    resolved = select_verified_replacement(
        sponsor=sponsor, runpod=runpod, verifier_factory=factory
    )

    assert resolved.selection.route == "sponsor_fallback"
    assert resolved.selection.model is sponsor
    assert resolved.verification is not None
    assert resolved.verification.models is not None
    assert resolved.verification.models.expected_model_found is False
    assert "configured model not advertised" in resolved.selection.reason


def test_runtime_failure_uses_sponsor_and_records_actual_route():
    sponsor = _model("sponsor", "https://sponsor.invalid/v1")
    runpod = _model("runpod", "https://runpod.invalid/v1")
    failover = ReplacementFailover(runpod, sponsor)

    async def primary():
        raise ConnectionError("pod disappeared after preflight")

    async def fallback():
        return {"report": "sponsor answered"}

    result = asyncio.run(failover.invoke(primary, fallback))

    assert result == {"report": "sponsor answered"}
    assert failover.last_use is not None
    assert failover.last_use.model is sponsor
    assert failover.last_use.route == "sponsor_fallback"
    assert failover.last_use.fallback_used is True
    assert "ConnectionError" in failover.last_use.reason


def test_runtime_success_records_runpod_without_fallback():
    sponsor = _model("sponsor", "https://sponsor.invalid/v1")
    runpod = _model("runpod", "https://runpod.invalid/v1")
    failover = ReplacementFailover(runpod, sponsor)

    async def primary():
        return {"report": "runpod answered"}

    async def fallback():
        raise AssertionError("fallback must not run")

    result = asyncio.run(failover.invoke(primary, fallback))

    assert result == {"report": "runpod answered"}
    assert failover.last_use is not None
    assert failover.last_use.model is runpod
    assert failover.last_use.route == "runpod"
    assert failover.last_use.fallback_used is False
