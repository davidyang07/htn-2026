"""Canonical benchmark matrix (Priority 1 of the product-validation brief):
12+ executable attack scenarios, 6+ defense configurations, at least one
adaptive-attacker preset, at least one Byzantine/security-plane attack, and
one 2,500+ agent scale run. Every entry is a plain ExperimentConfig (or
BenchmarkConfig for the scale run) -- app/benchmark/runner.py drives them
through the exact same deterministic engine already covered by
backend/tests/test_determinism.py et al. No new scenario logic is added
here; this module only chooses parameters for scenarios that already exist
in app/scenarios/registry.py.
"""

from __future__ import annotations

from app.benchmark.config import BenchmarkConfig
from app.schemas.experiment import ExperimentConfig

SEED = 42

ATTACK_SCENARIOS: dict[str, ExperimentConfig] = {
    "propagation_low_virulence": ExperimentConfig(
        seed=SEED, node_count=80, p_same=0.10, p_cross=0.02, defense_enabled=True,
    ),
    "propagation_high_virulence": ExperimentConfig(
        seed=SEED, node_count=80, p_same=0.35, p_cross=0.10, defense_enabled=True,
    ),
    "propagation_dense_network": ExperimentConfig(
        seed=SEED, node_count=80, edge_density=5, p_same=0.20, defense_enabled=True,
    ),
    "propagation_no_defense": ExperimentConfig(
        seed=SEED, node_count=80, p_same=0.20, defense_enabled=False,
    ),
    "adaptive_attacker_aggressive_bias": ExperimentConfig(
        seed=SEED,
        node_count=80,
        active_scenarios=["adaptive_attacker"],
        adaptive_detection_threshold=0.6,
        detector_sensitivity=0.3,
        defense_enabled=True,
    ),
    "adaptive_attacker_stealthy_bias": ExperimentConfig(
        seed=SEED,
        node_count=80,
        active_scenarios=["adaptive_attacker"],
        adaptive_detection_threshold=0.1,
        detector_sensitivity=0.3,
        defense_enabled=True,
    ),
    "false_quarantine_attack": ExperimentConfig(
        seed=SEED,
        node_count=80,
        sentinel_count=2,
        false_quarantine_rate=0.15,
        defense_enabled=True,
        detector_sensitivity=0.3,
    ),
    "sentinel_compromise_attack": ExperimentConfig(
        seed=SEED,
        node_count=80,
        active_scenarios=["propagation", "sentinel_compromise"],
        sentinel_count=2,
        sentinel_compromise_rate=0.3,
        defense_enabled=True,
    ),
    "attestation_replay_attack": ExperimentConfig(
        seed=SEED,
        node_count=80,
        active_scenarios=["propagation", "attestation"],
        sentinel_count=2,
        attestation_replay_rate=0.3,
        defense_enabled=True,
    ),
    "byzantine_collusion_attack": ExperimentConfig(
        seed=SEED,
        node_count=80,
        active_scenarios=["propagation", "byzantine_collusion"],
        credential_count=6,
        byzantine_collusion_rate=0.3,
        defense_enabled=True,
    ),
    "combined_byzantine_multi_vector": ExperimentConfig(
        seed=SEED,
        node_count=80,
        active_scenarios=[
            "propagation",
            "sentinel_compromise",
            "attestation",
            "byzantine_collusion",
        ],
        sentinel_count=3,
        credential_count=6,
        tool_count=6,
        resource_count=4,
        sentinel_compromise_rate=0.2,
        attestation_replay_rate=0.2,
        byzantine_collusion_rate=0.2,
        defense_enabled=True,
    ),
    "adaptive_plus_byzantine": ExperimentConfig(
        seed=SEED,
        node_count=80,
        active_scenarios=["adaptive_attacker", "sentinel_compromise", "attestation"],
        sentinel_count=2,
        sentinel_compromise_rate=0.25,
        attestation_replay_rate=0.2,
        adaptive_detection_threshold=0.3,
        defense_enabled=True,
    ),
    "prompt_injection_lateral": ExperimentConfig(
        seed=SEED,
        node_count=40,
        real_agent_count=8,
        model_provider="mock",
        active_scenarios=["propagation", "prompt_injection"],
        defense_enabled=True,
    ),
    "scale_run_2500_agents": BenchmarkConfig(
        seed=SEED,
        node_count=2500,
        edge_density=3,
        p_same=0.10,
        p_cross=0.02,
        defense_enabled=True,
        detector_sensitivity=0.3,
        max_ticks=60,
    ),
}

# Defense comparison: same attack, varying defense posture.
DEFENSE_BASE_ATTACK = ExperimentConfig(
    seed=SEED, node_count=80, p_same=0.25, p_cross=0.06, defense_enabled=True,
)

DEFENSE_VARIANTS: dict[str, dict] = {
    "defense_off": {"defense_enabled": False},
    "defense_low_sensitivity": {"defense_enabled": True, "detector_sensitivity": 0.2},
    "defense_medium_sensitivity": {"defense_enabled": True, "detector_sensitivity": 0.5},
    "defense_high_sensitivity": {"defense_enabled": True, "detector_sensitivity": 0.9},
    "defense_with_1_sentinel": {
        "defense_enabled": True, "detector_sensitivity": 0.3, "sentinel_count": 1,
    },
    "defense_with_3_sentinels": {
        "defense_enabled": True, "detector_sensitivity": 0.3, "sentinel_count": 3,
    },
    "defense_with_5_sentinels": {
        "defense_enabled": True, "detector_sensitivity": 0.3, "sentinel_count": 5,
    },
}

# Engineered so a sentinel is likely to be subverted mid-run (sentinel_count
# below the cap, so remediation.recommend() has room to raise it) --
# exercised end-to-end (including the actual before/after re-test) in
# app/benchmark/runner.py's remediation comparison, not here.
REMEDIATION_CASE = ExperimentConfig(
    seed=SEED,
    node_count=80,
    active_scenarios=["propagation", "sentinel_compromise"],
    sentinel_count=1,
    sentinel_compromise_rate=0.02,
    defense_enabled=True,
    detector_sensitivity=0.3,
)
