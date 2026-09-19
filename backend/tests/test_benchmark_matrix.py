from app.benchmark.matrix import (
    ATTACK_SCENARIOS,
    DEFENSE_VARIANTS,
    REMEDIATION_CASE,
)
from app.scenarios.registry import ASYNC_SCENARIOS, SYNC_SCENARIOS


def test_at_least_twelve_attack_scenarios():
    assert len(ATTACK_SCENARIOS) >= 12


def test_at_least_six_defense_variants():
    assert len(DEFENSE_VARIANTS) >= 6


def test_every_active_scenario_name_is_registered():
    all_names = set(SYNC_SCENARIOS) | set(ASYNC_SCENARIOS)
    for name, config in ATTACK_SCENARIOS.items():
        for scenario_name in config.active_scenarios:
            assert (
                scenario_name in all_names
            ), f"{name} references unknown scenario {scenario_name!r}"


def test_scale_run_preset_hits_2500_agents():
    scale_configs = [c for c in ATTACK_SCENARIOS.values() if c.node_count >= 2500]
    assert scale_configs, "no preset reaches the 2,500-agent scale requirement"


def test_at_least_one_byzantine_security_plane_attack_present():
    byzantine_names = {
        "false_quarantine", "sentinel_compromise", "attestation", "byzantine_collusion",
    }
    found = False
    for config in ATTACK_SCENARIOS.values():
        if set(config.active_scenarios) & byzantine_names or config.false_quarantine_rate > 0:
            found = True
    assert found


def test_at_least_one_adaptive_attacker_preset():
    assert any("adaptive_attacker" in c.active_scenarios for c in ATTACK_SCENARIOS.values())


def test_remediation_case_has_room_for_a_recommendation():
    assert REMEDIATION_CASE.sentinel_count > 0
    assert REMEDIATION_CASE.sentinel_count < 5
    assert REMEDIATION_CASE.sentinel_compromise_rate > 0
