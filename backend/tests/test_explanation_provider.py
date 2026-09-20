"""Provider resolution reuses WorkSwarm configuration without leaking keys."""

from types import SimpleNamespace

from app.config import Settings
from app.explanation.provider import resolve_explanation_provider


def test_workswarm_sponsor_model_is_preferred_without_direct_openai_key():
    settings = Settings(_env_file=None, openai_api_key=None)
    workswarm_model = SimpleNamespace(
        configured=True,
        provider="OpenRouter",
        model_name="sponsor/model",
        api_key="sponsor-secret",
        api_base="https://openrouter.ai/api/v1",
        source="workswarm config.yaml",
    )

    provider = resolve_explanation_provider(settings, lambda: workswarm_model)

    assert provider is not None
    assert provider.provider == "OpenRouter"
    assert provider.model == "sponsor/model"
    assert provider.chat_completions_url == "https://openrouter.ai/api/v1/chat/completions"
    assert provider.source == "workswarm config.yaml"
    assert "sponsor-secret" not in repr(provider)


def test_shared_agentshield_model_environment_is_the_container_fallback():
    settings = Settings(
        _env_file=None,
        agentshield_model_base_url="https://gateway.example/v1",
        agentshield_model_api_key="shared-secret",
        agentshield_model_name="shared/model",
        agentshield_model_provider="Sponsor Gateway",
        openai_api_key=None,
    )

    provider = resolve_explanation_provider(settings, lambda: None)

    assert provider is not None
    assert provider.provider == "Sponsor Gateway"
    assert provider.model == "shared/model"
    assert provider.source == "AGENTSHIELD_MODEL_*"


def test_absent_or_broken_provider_resolution_is_optional():
    settings = Settings(
        _env_file=None,
        agentshield_model_base_url=None,
        agentshield_model_name=None,
        openai_api_key=None,
    )

    assert resolve_explanation_provider(settings, lambda: None) is None

    def broken_resolver():
        raise RuntimeError("provider configuration unavailable")

    assert resolve_explanation_provider(settings, broken_resolver) is None
