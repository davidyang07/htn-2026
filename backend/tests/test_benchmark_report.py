import json

from app.benchmark.matrix import DEFENSE_BASE_ATTACK, DEFENSE_VARIANTS, REMEDIATION_CASE
from app.benchmark.report import build_report, render_markdown
from app.benchmark.runner import run_preset
from app.remediation.analyze import recommend


def _small_fixture_report():
    attack_runs = [
        run_preset("propagation_low_virulence", DEFENSE_BASE_ATTACK),
        run_preset(
            "defense_off_variant",
            DEFENSE_BASE_ATTACK.model_copy(update=DEFENSE_VARIANTS["defense_off"]),
        ),
    ]
    defense_runs = [
        run_preset(name, DEFENSE_BASE_ATTACK.model_copy(update=overrides))
        for name, overrides in DEFENSE_VARIANTS.items()
    ]
    before = run_preset("remediation_before", REMEDIATION_CASE)
    recs = recommend(
        REMEDIATION_CASE,
        compromise_fraction=before.metrics["compromise_fraction"],
        security_plane_integrity=before.metrics["security_plane_integrity"],
    )
    after = run_preset(
        "remediation_after", REMEDIATION_CASE.model_copy(update=recs[0].config_diff)
    )
    return build_report(attack_runs, defense_runs, before, after, recs[0])


def test_report_is_json_serializable():
    report = _small_fixture_report()
    json.dumps(report)


def test_report_contains_required_sections():
    report = _small_fixture_report()
    assert "attack_scenarios" in report
    assert "defense_comparison" in report
    assert "remediation" in report
    assert report["remediation"]["before"]["security_plane_integrity"] is not None
    assert report["remediation"]["after"]["security_plane_integrity"] is not None


def test_markdown_report_mentions_every_attack_scenario_name():
    report = _small_fixture_report()
    markdown = render_markdown(report)
    for run in report["attack_scenarios"]:
        assert run["name"] in markdown
