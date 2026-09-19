#!/usr/bin/env python3
"""Runs the canonical benchmark suite (Priority 1) and writes machine- and
human-readable artifacts to backend/.artifacts/benchmark/. Zero real
provider calls -- prompt_injection presets use MockProvider only."""

import json
import sys
from pathlib import Path

from app.benchmark.matrix import (
    ATTACK_SCENARIOS,
    DEFENSE_BASE_ATTACK,
    DEFENSE_VARIANTS,
    REMEDIATION_CASE,
)
from app.benchmark.report import build_report, render_markdown
from app.benchmark.runner import run_preset
from app.remediation.analyze import recommend

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / ".artifacts" / "benchmark"


def main() -> int:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    attack_runs = [run_preset(name, config) for name, config in ATTACK_SCENARIOS.items()]
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
    if not recs:
        print("FAIL: REMEDIATION_CASE did not trigger a recommendation", file=sys.stderr)
        return 1
    after = run_preset(
        "remediation_after", REMEDIATION_CASE.model_copy(update=recs[0].config_diff)
    )

    report = build_report(attack_runs, defense_runs, before, after, recs[0])

    (ARTIFACTS_DIR / "results.json").write_text(json.dumps(report, indent=2))
    (ARTIFACTS_DIR / "report.md").write_text(render_markdown(report))

    print(f"Wrote {ARTIFACTS_DIR / 'results.json'} and {ARTIFACTS_DIR / 'report.md'}")
    print(f"{len(attack_runs)} attack scenarios, {len(defense_runs)} defense variants.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
