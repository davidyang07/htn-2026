import json
import subprocess
import sys

from app.benchmark.cli import evaluate


def test_evaluate_findings_include_a_nonnegative_duration():
    findings = evaluate()
    assert findings
    for finding in findings:
        assert finding.duration_s >= 0.0


def test_cli_json_mode_prints_one_valid_json_object_with_all_findings():
    result = subprocess.run(
        [sys.executable, "scripts/agentshield_test.py", "--json"],
        capture_output=True,
        text=True,
        cwd=".",
    )
    payload = json.loads(result.stdout)
    assert "ok" in payload
    assert isinstance(payload["findings"], list)
    assert len(payload["findings"]) >= 2
    for finding in payload["findings"]:
        assert {"name", "passed", "detail", "duration_s"} <= finding.keys()
    assert result.returncode == (0 if payload["ok"] else 1)


def test_cli_text_mode_prints_a_summary_line():
    result = subprocess.run(
        [sys.executable, "scripts/agentshield_test.py"],
        capture_output=True,
        text=True,
        cwd=".",
    )
    assert "PASS" in result.stdout or "FAIL" in result.stdout
    assert "/" in result.stdout.splitlines()[-1]  # e.g. "2/2 findings passed in 1.2s"
