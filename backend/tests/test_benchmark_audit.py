import pytest

from app.benchmark.audit import (
    _candidate_configs,
    audit_coverage,
    audit_remediation_candidates,
    build_audit_report,
    render_audit_markdown,
    strongest_candidate,
)
from app.benchmark.matrix import ATTACK_SCENARIOS, DEFENSE_VARIANTS
from app.schemas.experiment import ExperimentConfig


# The sweep is 98 real attack x defense simulations plus a re-test of every
# one that triggers a recommendation -- roughly two minutes of real engine
# work. Every preset is seeded, so the result is deterministic: running it
# once per module and sharing it keeps every assertion below measuring the
# real sweep without paying for it five times over.
@pytest.fixture(scope="module")
def candidates():
    return audit_remediation_candidates()


def test_audit_sweeps_the_full_attack_by_defense_cross_product():
    # The audit's stated scope is every attack scenario under every defense
    # posture, not just each preset on its own.
    attacks = [n for n, c in ATTACK_SCENARIOS.items() if isinstance(c, ExperimentConfig)]
    configs = _candidate_configs()
    for attack in attacks:
        for defense in DEFENSE_VARIANTS:
            assert f"{attack}__{defense}" in configs
    # ... and the standalone presets are still swept alongside it.
    for attack in attacks:
        assert attack in configs
    for defense in DEFENSE_VARIANTS:
        assert f"defense_variant_{defense}" in configs


def test_cross_product_configs_apply_the_defense_override_to_the_attack():
    configs = _candidate_configs()
    combined = configs["propagation_high_virulence__defense_off"]
    base = ATTACK_SCENARIOS["propagation_high_virulence"]
    assert combined.defense_enabled is False  # the defense override won
    assert combined.p_same == base.p_same  # the attack parameters survived


def test_audit_coverage_matches_the_configs_actually_swept():
    coverage = audit_coverage()
    attacks = [n for n, c in ATTACK_SCENARIOS.items() if isinstance(c, ExperimentConfig)]
    assert coverage["attack_scenarios"] == len(attacks)
    assert coverage["defense_variants"] == len(DEFENSE_VARIANTS)
    assert coverage["cross_product_configs"] == len(attacks) * len(DEFENSE_VARIANTS)
    assert coverage["configs_swept"] == len(_candidate_configs())


def test_audit_finds_at_least_the_three_known_spi_candidates(candidates):
    # sentinel_compromise_attack, combined_byzantine_multi_vector, and
    # adaptive_plus_byzantine are already known (backend/.artifacts/
    # benchmark/results.json) to have security_plane_integrity < 1.0, so
    # recommend() must fire a sentinel_count recommendation for each.
    names = {c.name for c in candidates}
    assert "sentinel_compromise_attack" in names
    assert "combined_byzantine_multi_vector" in names
    assert "adaptive_plus_byzantine" in names


def test_audit_finds_the_no_defense_candidate(candidates):
    # propagation_no_defense has compromise_fraction=1.0 and
    # defense_enabled=False, so recommend() must fire an "enable defense"
    # recommendation for it too.
    names = {c.name for c in candidates}
    assert "propagation_no_defense" in names


def test_audit_produces_a_result_for_every_triggered_candidate(candidates):
    # Not every recommendation actually improves retained_utility once
    # re-tested for real: raising sentinel_count grows the security-plane
    # node pool that security_plane_integrity's denominator counts over, so
    # for the combined/adaptive Byzantine presets it can measurably worsen
    # both security_plane_integrity and retained_utility (a real, surprising
    # result this audit exists to surface honestly, not to hide). The full
    # cross product shows the sentinel_count branch is posture-dependent
    # rather than useless: under defense_medium_sensitivity it takes
    # sentinel_compromise_attack from 0.0 to 0.9625 retained_utility, while
    # under adaptive_plus_byzantine's own posture it measurably regresses.
    # So this only asserts every triggered candidate produced a real
    # before/after measurement, not that all of them improved.
    assert candidates
    for c in candidates:
        assert isinstance(c.before.metrics["retained_utility"], float)
        assert isinstance(c.after.metrics["retained_utility"], float)


def test_strongest_candidate_has_the_largest_retained_utility_delta(candidates):
    strongest = strongest_candidate(candidates)
    deltas = [
        c.after.metrics["retained_utility"] - c.before.metrics["retained_utility"]
        for c in candidates
    ]
    assert (
        strongest.after.metrics["retained_utility"] - strongest.before.metrics["retained_utility"]
        == max(deltas)
    )


def test_build_and_render_audit_report_is_json_and_markdown_safe(candidates):
    strongest = strongest_candidate(candidates)
    report = build_audit_report(candidates, strongest)
    assert report["strongest"]["name"] == strongest.name
    assert len(report["candidates"]) == len(candidates)
    assert report["coverage"]["candidates_triggered"] == len(candidates)
    markdown = render_audit_markdown(report)
    assert strongest.name in markdown
    assert "|" in markdown  # a markdown table was rendered
    # The artifact states its own coverage rather than relying on the docs.
    assert f"Swept {report['coverage']['configs_swept']} configurations" in markdown
    # Every candidate is a row, so nothing is silently truncated.
    for candidate in candidates:
        assert candidate.name in markdown
