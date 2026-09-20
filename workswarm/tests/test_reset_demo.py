"""Reset remains safe and repeatable without mutating the real demo target."""

import subprocess
from pathlib import Path

from workswarm import reset_demo
from workswarm.verify import TestRun as DemoTestRun


def _completed(*args: str, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")


def test_generated_file_cleanup_is_repeatable_and_name_bounded(
    tmp_path: Path, monkeypatch
) -> None:
    sandbox = tmp_path / "demo_target"
    generated = sandbox / "tests" / "test_auth_regression.py"
    generated.parent.mkdir(parents=True)
    generated.write_text("synthetic regression", encoding="utf-8")
    keep = sandbox / "tests" / "keep.py"
    keep.write_text("keep", encoding="utf-8")

    monkeypatch.setattr(reset_demo, "DEMO_TARGET", sandbox)
    monkeypatch.setattr(reset_demo, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(reset_demo, "_git", lambda *args: _completed(*args))

    first = reset_demo.remove_generated_files()
    second = reset_demo.remove_generated_files()

    assert first == "removed tests/test_auth_regression.py"
    assert second == "no generated files to remove"
    assert not generated.exists()
    assert keep.read_text(encoding="utf-8") == "keep"


def test_tracked_restore_uses_the_committed_demo_target_only(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return _completed(*args)

    monkeypatch.setattr(reset_demo, "_git", fake_git)

    result = reset_demo.restore_tracked_baseline()

    assert result == "restored every tracked file under demo_target/ from git"
    assert calls == [
        ("ls-files", "--error-unmatch", "demo_target/app/auth.py"),
        ("checkout", "--", "demo_target"),
    ]


def test_vulnerable_baseline_check_rejects_a_patched_module(
    tmp_path: Path, monkeypatch
) -> None:
    sandbox = tmp_path / "demo_target"
    auth = sandbox / "app" / "auth.py"
    auth.parent.mkdir(parents=True)
    monkeypatch.setattr(reset_demo, "DEMO_TARGET", sandbox)

    auth.write_text("# token expired\n", encoding="utf-8")
    try:
        reset_demo.verify_vulnerable_baseline()
    except SystemExit as exc:
        assert "still contains the fix" in str(exc)
    else:
        raise AssertionError("patched baseline was accepted")

    auth.write_text("# vulnerable baseline\n", encoding="utf-8")
    assert reset_demo.verify_vulnerable_baseline() == (
        "confirmed auth.py is the vulnerable baseline"
    )


def test_main_can_run_twice_and_rechecks_the_baseline_each_time(
    monkeypatch, capsys
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(reset_demo, "remove_generated_files", lambda: "clean")
    monkeypatch.setattr(reset_demo, "restore_tracked_baseline", lambda: "restored")

    def verify() -> str:
        calls.append("verify")
        return "vulnerable"

    monkeypatch.setattr(reset_demo, "verify_vulnerable_baseline", verify)
    monkeypatch.setattr(reset_demo, "clear_runtime_sessions", lambda: "cleared")
    monkeypatch.setattr(
        reset_demo,
        "run_demo_target_tests",
        lambda: DemoTestRun(
            command="pytest demo_target",
            exit_code=0,
            passed=True,
            summary="6 passed",
            stdout="6 passed",
        ),
    )

    assert reset_demo.main() == 0
    assert reset_demo.main() == 0
    assert calls == ["verify", "verify"]
    assert capsys.readouterr().out.count("Baseline restored. Ready for another run.") == 2
