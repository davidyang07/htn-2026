#!/usr/bin/env python3
"""agentshield test: CI-friendly pass/fail gate over a fast subset of the
benchmark suite + golden demo. Exit 0 if every finding passes, else 1.
Pass --json for a single machine-readable line (CI log parsers, dashboards)
instead of the default human-readable PASS/FAIL lines."""

import argparse
import json
import time
from dataclasses import asdict

from app.benchmark.cli import evaluate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    args = parser.parse_args()

    start = time.monotonic()
    findings = evaluate()
    total_duration = time.monotonic() - start
    ok = all(f.passed for f in findings)
    passed_count = sum(1 for f in findings if f.passed)

    if args.json:
        payload = {
            "ok": ok,
            "findings": [asdict(f) for f in findings],
            "duration_s": round(total_duration, 4),
        }
        print(json.dumps(payload))
    else:
        for finding in findings:
            status = "PASS" if finding.passed else "FAIL"
            print(f"[{status}] {finding.name}: {finding.detail} ({finding.duration_s:.2f}s)")
        print(f"{passed_count}/{len(findings)} findings passed in {total_duration:.2f}s")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
