from workswarm.config import ModelConfig, NO_MODEL
from workswarm.replacement_provider import select_replacement_provider


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
