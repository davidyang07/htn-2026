import httpx

import workswarm.config as model_config
from workswarm.config import NO_MODEL, ModelConfig, resolve_model, resolve_runpod_model
from workswarm.replacement_provider import (
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
