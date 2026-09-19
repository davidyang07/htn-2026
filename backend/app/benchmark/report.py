"""Aggregates BenchmarkRun results into a machine-readable dict (JSON) and a
human-readable Markdown summary -- Priority 1's "machine-readable and
human-readable benchmark artifacts" deliverable. Every number here is copied
straight out of a BenchmarkRun.metrics dict already computed by
app/metrics/compute.py's pure functions -- nothing is invented here.
"""

from __future__ import annotations

from typing import Any

from app.benchmark.runner import BenchmarkRun
from app.remediation.analyze import Recommendation


def _run_summary(run: BenchmarkRun) -> dict[str, Any]:
    return {
        "name": run.name,
        "seed": run.config.seed,
        "node_count": run.config.node_count,
        "active_scenarios": list(run.config.active_scenarios),
        "duration_s": round(run.duration_s, 4),
        **run.metrics,
    }


def build_report(
    attack_runs: list[BenchmarkRun],
    defense_runs: list[BenchmarkRun],
    remediation_before: BenchmarkRun,
    remediation_after: BenchmarkRun,
    recommendation: Recommendation,
) -> dict[str, Any]:
    return {
        "attack_scenarios": [_run_summary(r) for r in attack_runs],
        "defense_comparison": [_run_summary(r) for r in defense_runs],
        "remediation": {
            "recommendation": recommendation.description,
            "config_diff": recommendation.config_diff,
            "before": _run_summary(remediation_before),
            "after": _run_summary(remediation_after),
        },
    }


def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, separator]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(c, "")) for c in columns) + " |")
    return "\n".join(lines)


ATTACK_COLUMNS = [
    "name",
    "node_count",
    "compromise_fraction",
    "retained_utility",
    "blast_radius_fraction",
    "privileged_exposure",
    "security_plane_integrity",
    "attack_success_rate",
    "false_quarantine_rate",
    "detection_latency",
    "containment_latency",
    "duration_s",
]

DEFENSE_COLUMNS = ["name", "attack_success_rate", "retained_utility", "compromise_fraction"]


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# AgentShield Canonical Benchmark Report", ""]
    lines.append(
        f"{len(report['attack_scenarios'])} attack scenarios, "
        f"{len(report['defense_comparison'])} defense configurations."
    )
    lines.append("")
    lines.append("## Attack scenarios")
    lines.append(_markdown_table(report["attack_scenarios"], ATTACK_COLUMNS))
    lines.append("")
    lines.append("## Defense comparison (same attack, varying defense posture)")
    lines.append(_markdown_table(report["defense_comparison"], DEFENSE_COLUMNS))
    lines.append("")
    lines.append("## Remediation before/after")
    rem = report["remediation"]
    lines.append(f"**Recommendation:** {rem['recommendation']}")
    lines.append(f"**Config diff:** `{rem['config_diff']}`")
    lines.append("")
    lines.append(_markdown_table([rem["before"], rem["after"]], ATTACK_COLUMNS))
    return "\n".join(lines)
