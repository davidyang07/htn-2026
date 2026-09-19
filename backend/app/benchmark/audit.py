"""Priority 2 of this session's brief: audits every attack-scenario and
defense-variant preset already defined in app/benchmark/matrix.py for a
remediation opportunity, re-tests each one exactly like the fixed
REMEDIATION_CASE already does in run_benchmark.py, and surfaces the single
candidate with the largest measured retained_utility improvement -- the
strongest real remediation result across the full matrix, not just the one
hand-picked case. Reuses run_preset and recommend() verbatim; no new
simulation or remediation logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.benchmark.matrix import ATTACK_SCENARIOS, DEFENSE_BASE_ATTACK, DEFENSE_VARIANTS
from app.benchmark.runner import BenchmarkRun, run_preset
from app.remediation.analyze import Recommendation, recommend
from app.schemas.experiment import ExperimentConfig


@dataclass
class AuditCandidate:
    name: str
    recommendation: Recommendation
    before: BenchmarkRun
    after: BenchmarkRun

    @property
    def retained_utility_delta(self) -> float:
        return self.after.metrics["retained_utility"] - self.before.metrics["retained_utility"]

    @property
    def security_plane_integrity_delta(self) -> float:
        return (
            self.after.metrics["security_plane_integrity"]
            - self.before.metrics["security_plane_integrity"]
        )

    @property
    def compromise_fraction_delta(self) -> float:
        return (
            self.after.metrics["compromise_fraction"]
            - self.before.metrics["compromise_fraction"]
        )


def _attack_configs() -> dict[str, ExperimentConfig]:
    """All 14 attack scenarios app/benchmark/matrix.py defines. The
    isinstance filter admits the 2,500-agent scale run too -- BenchmarkConfig
    is an ExperimentConfig subclass (app/benchmark/config.py), so recommend()
    and model_copy() both accept it -- and only guards against a future
    non-ExperimentConfig entry being added to ATTACK_SCENARIOS."""
    return {
        name: config
        for name, config in ATTACK_SCENARIOS.items()
        if isinstance(config, ExperimentConfig)
    }


def _candidate_configs() -> dict[str, ExperimentConfig]:
    """The full attack-scenario x defense-posture sweep: every attack
    scenario on its own, every defense variant of the fixed
    defense-comparison attack on its own, and -- the actual cross product --
    every attack scenario re-run under every one of the 7 defense postures
    (`{attack}__{defense}`). The standalone presets are kept alongside the
    cross product so each scenario's own tuned defense parameters stay
    directly comparable to the 7 uniform postures imposed on top of it."""
    attacks = _attack_configs()
    configs: dict[str, ExperimentConfig] = dict(attacks)
    for name, overrides in DEFENSE_VARIANTS.items():
        configs[f"defense_variant_{name}"] = DEFENSE_BASE_ATTACK.model_copy(update=overrides)
    for attack_name, attack in attacks.items():
        for defense_name, overrides in DEFENSE_VARIANTS.items():
            configs[f"{attack_name}__{defense_name}"] = attack.model_copy(update=overrides)
    return configs


def audit_remediation_candidates() -> list[AuditCandidate]:
    candidates: list[AuditCandidate] = []
    for name, config in _candidate_configs().items():
        before = run_preset(name, config)
        recs = recommend(
            config,
            compromise_fraction=before.metrics["compromise_fraction"],
            security_plane_integrity=before.metrics["security_plane_integrity"],
        )
        if not recs:
            continue
        after = run_preset(f"{name}_remediated", config.model_copy(update=recs[0].config_diff))
        candidates.append(
            AuditCandidate(name=name, recommendation=recs[0], before=before, after=after)
        )
    return candidates


def strongest_candidate(candidates: list[AuditCandidate]) -> AuditCandidate:
    return max(candidates, key=lambda c: c.retained_utility_delta)


def _candidate_summary(c: AuditCandidate) -> dict[str, Any]:
    return {
        "name": c.name,
        "recommendation": c.recommendation.description,
        "config_diff": c.recommendation.config_diff,
        "retained_utility_before": c.before.metrics["retained_utility"],
        "retained_utility_after": c.after.metrics["retained_utility"],
        "retained_utility_delta": c.retained_utility_delta,
        "security_plane_integrity_before": c.before.metrics["security_plane_integrity"],
        "security_plane_integrity_after": c.after.metrics["security_plane_integrity"],
        "compromise_fraction_before": c.before.metrics["compromise_fraction"],
        "compromise_fraction_after": c.after.metrics["compromise_fraction"],
    }


def audit_coverage() -> dict[str, int]:
    """The exact shape of the sweep, so the artifacts state their own
    coverage instead of the docs having to assert it separately."""
    attacks = _attack_configs()
    return {
        "attack_scenarios": len(attacks),
        "defense_variants": len(DEFENSE_VARIANTS),
        "cross_product_configs": len(attacks) * len(DEFENSE_VARIANTS),
        "configs_swept": len(_candidate_configs()),
    }


def build_audit_report(
    candidates: list[AuditCandidate], strongest: AuditCandidate
) -> dict[str, Any]:
    coverage = audit_coverage()
    return {
        "coverage": {**coverage, "candidates_triggered": len(candidates)},
        "candidates": [_candidate_summary(c) for c in candidates],
        "strongest": _candidate_summary(strongest),
    }


def render_audit_markdown(report: dict[str, Any]) -> str:
    columns = [
        "name",
        "recommendation",
        "retained_utility_before",
        "retained_utility_after",
        "retained_utility_delta",
        "security_plane_integrity_before",
        "security_plane_integrity_after",
    ]
    coverage = report.get("coverage", {})
    ranked = sorted(report["candidates"], key=lambda c: -c["retained_utility_delta"])
    regressions = [c for c in ranked if c["retained_utility_delta"] < 0]

    lines = ["# AgentShield Remediation Audit", ""]
    if coverage:
        lines.append(
            f"Swept {coverage['configs_swept']} configurations: "
            f"{coverage['attack_scenarios']} attack scenarios x "
            f"{coverage['defense_variants']} defense postures "
            f"({coverage['cross_product_configs']} combinations) plus each preset standalone."
        )
    lines.append(
        f"{len(report['candidates'])} of them triggered a remediation recommendation, "
        "each re-tested for real and ranked below by measured retained_utility improvement."
    )
    lines.append("")
    lines.append("## Strongest result")
    strongest = report["strongest"]
    lines.append(f"**{strongest['name']}**: {strongest['recommendation']}")
    lines.append(
        f"retained_utility {strongest['retained_utility_before']:.4f} -> "
        f"{strongest['retained_utility_after']:.4f} "
        f"(+{strongest['retained_utility_delta']:.4f})"
    )
    lines.append("")
    if regressions:
        # Surfaced, not hidden: raising sentinel_count grows the pool
        # security_plane_integrity is measured over, so some recommendations
        # measurably make things worse once re-tested. See
        # tests/test_benchmark_audit.py.
        lines.append(
            f"{len(regressions)} of the {len(ranked)} recommendations measurably *worsened* "
            "retained_utility once re-tested; they are listed at the bottom of the table below."
        )
        lines.append("")
    lines.append("## All candidates")
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    lines.append(header)
    lines.append(separator)
    for row in ranked:
        cells = [
            f"{row[c]:.4f}" if isinstance(row[c], float) else str(row[c]) for c in columns
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
