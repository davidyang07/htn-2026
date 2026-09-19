"""agentshield test: runs a fixed, fast subset of the benchmark matrix plus
the golden demo, checks concrete pass/fail criteria, and returns findings.
Excludes the 2,500-agent scale run and the full 14-scenario attack matrix
(too slow for a CI gate) -- those stay a manual `make benchmark` command;
see README's benchmark section.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.benchmark.golden_demo import run_golden_demo
from app.benchmark.matrix import DEFENSE_BASE_ATTACK, DEFENSE_VARIANTS
from app.benchmark.runner import run_preset


@dataclass
class Finding:
    name: str
    passed: bool
    detail: str
    duration_s: float


def evaluate() -> list[Finding]:
    findings: list[Finding] = []

    start = time.monotonic()
    off = run_preset(
        "defense_off", DEFENSE_BASE_ATTACK.model_copy(update=DEFENSE_VARIANTS["defense_off"])
    )
    high = run_preset(
        "defense_high_sensitivity",
        DEFENSE_BASE_ATTACK.model_copy(update=DEFENSE_VARIANTS["defense_high_sensitivity"]),
    )
    passed = high.metrics["retained_utility"] >= off.metrics["retained_utility"]
    findings.append(
        Finding(
            name="high-sensitivity defense retains at least as much utility as no defense",
            passed=passed,
            detail=(
                f"defense_off retained_utility={off.metrics['retained_utility']:.2f}, "
                f"defense_high_sensitivity={high.metrics['retained_utility']:.2f}"
            ),
            duration_s=time.monotonic() - start,
        )
    )

    start = time.monotonic()
    demo = run_golden_demo()
    demo_passed = demo.rerun is not None and (
        demo.rerun.metrics["security_plane_integrity"]
        >= demo.baseline.metrics["security_plane_integrity"]
    )
    findings.append(
        Finding(
            name="golden demo remediation improves security_plane_integrity",
            passed=demo_passed,
            detail=(
                f"baseline={demo.baseline.metrics['security_plane_integrity']:.2f}, "
                f"rerun={(demo.rerun.metrics['security_plane_integrity'] if demo.rerun else None)}"
            ),
            duration_s=time.monotonic() - start,
        )
    )

    return findings
