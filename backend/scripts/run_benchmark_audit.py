#!/usr/bin/env python3
"""Priority 2: audits every attack-scenario/defense-variant preset for a
remediation opportunity and writes the ranked results to
backend/.artifacts/benchmark/{audit.json,audit.md}. Separate from
run_benchmark.py's single fixed REMEDIATION_CASE -- this sweeps the whole
matrix to surface the single strongest real remediation result.
"""

import json
from pathlib import Path

from app.benchmark.audit import (
    audit_remediation_candidates,
    build_audit_report,
    render_audit_markdown,
    strongest_candidate,
)

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / ".artifacts" / "benchmark"


def main() -> int:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    candidates = audit_remediation_candidates()
    if not candidates:
        print("no remediation candidates found in the benchmark matrix")
        return 1
    strongest = strongest_candidate(candidates)
    report = build_audit_report(candidates, strongest)

    (ARTIFACTS_DIR / "audit.json").write_text(json.dumps(report, indent=2))
    (ARTIFACTS_DIR / "audit.md").write_text(render_audit_markdown(report))

    print(f"Strongest result: {strongest.name} -- {strongest.recommendation.description}")
    print(
        f"retained_utility {strongest.before.metrics['retained_utility']:.4f} -> "
        f"{strongest.after.metrics['retained_utility']:.4f}"
    )
    print(f"Wrote {ARTIFACTS_DIR / 'audit.json'} and {ARTIFACTS_DIR / 'audit.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
