"""The real `pytest demo_target` run (docs/MVP_PLAN.md P0.10).

A subprocess, an exit code, and pytest's own summary line, verbatim. Nothing
here interprets, softens or reconstructs the result: a red run is reported red,
and that honesty is the entire reason a real test run is in the demo instead of
a claim.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass

from workswarm.config import DEMO_TARGET, REPO_ROOT

#: pytest's final status line, e.g. "8 passed in 0.08s" or
#: "1 failed, 7 passed in 0.21s".
#: pytest's own final status line. The alternation is longest-first on
#: purpose: with "error" before "errors", "2 errors in 0.30s" would capture
#: as "2 error" and drop the timing.
SUMMARY_RE = re.compile(
    r"^(?:=+\s*)?((?:\d+\s+(?:passed|failed|errors|error|skipped|xfailed|xpassed|warnings?)"
    r"(?:,\s*)?)+(?:\s+in\s+[\d.]+s)?)",
    re.MULTILINE,
)

TIMEOUT_S = 180


@dataclass(frozen=True)
class TestRun:
    command: str
    exit_code: int
    passed: bool
    summary: str
    stdout: str

    @property
    def tail(self) -> str:
        return "\n".join(self.stdout.strip().splitlines()[-40:])


def _summary_line(stdout: str) -> str:
    """pytest's own words. Falls back to the last non-empty line rather than
    inventing a sentence."""
    matches = SUMMARY_RE.findall(stdout)
    if matches:
        return matches[-1].strip()
    for line in reversed(stdout.strip().splitlines()):
        cleaned = line.strip().strip("=").strip()
        if cleaned:
            return cleaned
    return "pytest produced no output"


def run_demo_target_tests(python: str | None = None) -> TestRun:
    """Run `pytest demo_target` for real and report exactly what it said."""
    executable = python or sys.executable
    # No `-q` here: demo_target/pytest.ini already sets it, and a second one
    # means `-qq`, which suppresses the very summary line the demo quotes.
    args = [executable, "-m", "pytest", str(DEMO_TARGET), "--no-header"]
    command = "pytest demo_target"

    try:
        completed = subprocess.run(
            args,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return TestRun(
            command=command,
            exit_code=-1,
            passed=False,
            summary=f"pytest timed out after {TIMEOUT_S}s",
            stdout="",
        )

    stdout = (completed.stdout or "") + (completed.stderr or "")
    return TestRun(
        command=command,
        exit_code=completed.returncode,
        # The exit code is the authority, not the summary text.
        passed=completed.returncode == 0,
        summary=_summary_line(stdout),
        stdout=stdout,
    )
