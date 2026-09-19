from app.benchmark.golden_demo import GOLDEN_DEMO_CONFIG
from app.benchmark.matrix import ATTACK_SCENARIOS


def test_golden_demo_config_accepts_vllm_provider_override():
    config = GOLDEN_DEMO_CONFIG.model_copy(update={"model_provider": "vllm"})
    assert config.model_provider == "vllm"


def test_prompt_injection_preset_accepts_vllm_provider_override():
    config = ATTACK_SCENARIOS["prompt_injection_lateral"].model_copy(
        update={"model_provider": "vllm"}
    )
    assert config.model_provider == "vllm"
    assert config.real_agent_count > 0
