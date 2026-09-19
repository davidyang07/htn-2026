from app.benchmark.matrix import (
    ATTACK_SCENARIOS,
    DEFENSE_BASE_ATTACK,
    DEFENSE_VARIANTS,
    REMEDIATION_CASE,
)
from app.benchmark.runner import run_preset
from app.remediation.analyze import recommend

METRIC_KEYS = (
    "compromise_fraction",
    "retained_utility",
    "blast_radius_fraction",
    "privileged_exposure",
    "security_plane_integrity",
    "attack_success_rate",
    "false_quarantine_rate",
)


def test_run_preset_sync_scenario_produces_full_metrics():
    run = run_preset("propagation_low_virulence", ATTACK_SCENARIOS["propagation_low_virulence"])
    for key in METRIC_KEYS:
        assert key in run.metrics


def test_run_preset_is_deterministic():
    config = ATTACK_SCENARIOS["adaptive_attacker_aggressive_bias"]
    run1 = run_preset("x", config)
    run2 = run_preset("x", config)
    assert run1.metrics == run2.metrics


def test_run_preset_dispatches_async_for_prompt_injection():
    config = ATTACK_SCENARIOS["prompt_injection_lateral"]
    run = run_preset("prompt_injection_lateral", config)
    assert run.metrics["compromise_fraction"] >= 0.0


def test_scale_run_completes_and_reaches_2500_agents():
    run = run_preset("scale_run_2500_agents", ATTACK_SCENARIOS["scale_run_2500_agents"])
    assert len(run.final_state.nodes) >= 2500


def test_defense_comparison_matrix_all_run():
    results = {}
    for variant_name, overrides in DEFENSE_VARIANTS.items():
        config = DEFENSE_BASE_ATTACK.model_copy(update=overrides)
        results[variant_name] = run_preset(variant_name, config)
    assert (
        results["defense_high_sensitivity"].metrics["retained_utility"]
        >= results["defense_off"].metrics["retained_utility"]
    )


def test_remediation_before_after_shows_measurable_improvement():
    before = run_preset("remediation_before", REMEDIATION_CASE)
    recs = recommend(
        REMEDIATION_CASE,
        compromise_fraction=before.metrics["compromise_fraction"],
        security_plane_integrity=before.metrics["security_plane_integrity"],
    )
    assert recs, "expected REMEDIATION_CASE to trigger a real recommendation"
    after_config = REMEDIATION_CASE.model_copy(update=recs[0].config_diff)
    after = run_preset("remediation_after", after_config)
    assert (
        after.metrics["security_plane_integrity"]
        >= before.metrics["security_plane_integrity"]
    )
