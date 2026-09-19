"""Regression test for a bug found while building the benchmark harness:
app/engine/propagation.py, app/security/detection.py (quarantine path), and
app/scenarios/adaptive_attacker_scenario.py all constructed a fresh
WorldState without carrying forward `compromised_graph_nodes`, silently
resetting any sentinel/credential/security-control compromise to empty
every tick they ran -- which broke the sentinel_compromise/
byzantine_collusion scenarios' documented "stays compromised" persistence
whenever composed with propagation (their intended, documented use, per
docs/PLAN.md §5's own worked examples). No existing test caught this because
the runner integration test only asserted "finished" and "deterministic",
never accumulated graph-node compromise across ticks.
"""

from app.engine.tick import advance
from app.engine.topology import build_world
from app.schemas.experiment import ExperimentConfig


def test_sentinel_compromise_persists_across_propagation_ticks():
    config = ExperimentConfig(
        seed=42,
        node_count=25,
        max_ticks=15,
        sentinel_count=1,
        active_scenarios=["propagation", "sentinel_compromise"],
        sentinel_compromise_rate=1.0,
        defense_enabled=False,
    )
    state, _ = build_world(config)
    for _ in range(15):
        state, _ = advance(state, config)
    assert "sentinel-000" in state.compromised_graph_nodes


def test_sentinel_compromise_persists_through_a_legitimate_quarantine_tick():
    """detection.step's quarantine branch (defense_enabled=True) must not
    wipe an already-recorded sentinel/credential compromise either."""
    config = ExperimentConfig(
        seed=42,
        node_count=25,
        max_ticks=15,
        sentinel_count=1,
        active_scenarios=["propagation", "sentinel_compromise"],
        sentinel_compromise_rate=1.0,
        defense_enabled=True,
        detector_sensitivity=1.0,
    )
    state, _ = build_world(config)
    for _ in range(15):
        state, _ = advance(state, config)
    assert "sentinel-000" in state.compromised_graph_nodes
