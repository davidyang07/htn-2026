"""Reset the demo between runs.

    python workswarm/reset_demo.py

Restores `demo_target/` to its committed vulnerable baseline, removes the
files the Developer generated, clears AgentShield's live sessions, and then
*proves* the baseline is back by running the suite.

Two things this deliberately does NOT do:

* **It never runs `git clean -fd demo_target/`.** While `demo_target/` was
  untracked, that command deleted the entire demo target instead of resetting
  it. This removes individually named untracked *files* and never a directory,
  so the worst case is a leftover file, not a missing demo.
* **It never trusts a textual revert alone.** A model-written patch will not
  match any stored string, so the primary mechanism is `git checkout --`,
  which restores whatever the committed baseline actually is.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402

from workswarm.config import DEMO_TARGET, agentshield_base_url  # noqa: E402
from workswarm.verify import run_demo_target_tests  # noqa: E402

#: The marker the patched module contains and the vulnerable one does not.
PATCHED_MARKER = "token expired"

#: Files the Developer generates. Removed by name -- never by wildcard, never
#: by directory.
GENERATED_FILES = ("tests/test_auth_regression.py",)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _is_tracked(relative: str) -> bool:
    return _git("ls-files", "--error-unmatch", relative).returncode == 0


def restore_tracked_baseline() -> str:
    """Restore every tracked file under demo_target/ from the index/HEAD.

    This is the mechanism that works for a model-written patch: it does not
    care what the patch said, only what the committed baseline is.
    """
    if not _is_tracked("demo_target/app/auth.py"):
        return (
            "demo_target/ is NOT tracked by git, so there is no committed baseline "
            "to restore from -- falling back to the textual revert"
        )

    result = _git("checkout", "--", "demo_target")
    if result.returncode != 0:
        raise SystemExit(
            "git checkout -- demo_target failed:\n"
            f"{result.stderr.strip()}\n"
            "Restore demo_target/ by hand before running the demo again."
        )
    return "restored every tracked file under demo_target/ from git"


def remove_generated_files() -> str:
    """Delete exactly the files the Developer writes, by name.

    Each path is resolved and checked to be inside demo_target/ before
    unlinking, and only regular files are ever removed.
    """
    sandbox = DEMO_TARGET.resolve()
    removed: list[str] = []

    for relative in GENERATED_FILES:
        target = (sandbox / relative).resolve()
        if not target.is_relative_to(sandbox):
            raise SystemExit(f"refusing to delete {target}: outside demo_target/")
        if target.is_file():
            target.unlink()
            removed.append(relative)

    # Anything else the run left untracked inside demo_target/, named
    # individually by git. Directories are never passed to unlink().
    listed = _git("ls-files", "--others", "--exclude-standard", "demo_target")
    if listed.returncode == 0:
        for line in listed.stdout.splitlines():
            relative_to_repo = line.strip()
            if not relative_to_repo:
                continue
            target = (REPO_ROOT / relative_to_repo).resolve()
            if not target.is_relative_to(sandbox) or not target.is_file():
                continue
            target.unlink()
            removed.append(str(target.relative_to(sandbox)).replace("\\", "/"))

    if not removed:
        return "no generated files to remove"
    return "removed " + ", ".join(sorted(set(removed)))


def fallback_textual_revert() -> str:
    """Last resort when demo_target/ is not tracked yet.

    Only handles the deterministic patch; a model-written one cannot be
    reverted this way, and saying so is better than half-reverting it.
    """
    path = DEMO_TARGET / "app" / "auth.py"
    source = path.read_text(encoding="utf-8")
    if PATCHED_MARKER not in source:
        return "auth.py was already at the vulnerable baseline"

    from workswarm.patcher import PATCHED_BLOCK, VULNERABLE_BLOCK

    if PATCHED_BLOCK in source:
        path.write_text(source.replace(PATCHED_BLOCK, VULNERABLE_BLOCK), encoding="utf-8")
        return "auth.py restored to the vulnerable baseline (textual revert)"

    raise SystemExit(
        "demo_target/app/auth.py was patched by a model and demo_target/ is not\n"
        "tracked by git, so it cannot be reverted automatically.\n"
        "Commit demo_target/ (then `git checkout -- demo_target` works), or\n"
        "restore the file by hand."
    )


def verify_vulnerable_baseline() -> str:
    """Prove the restored module is the *vulnerable* one, not a patched one.

    A reset that silently restored a patched baseline would make every later
    run's vulnerability proof impossible, and the failure would surface
    somewhere far less obvious than here.
    """
    source = (DEMO_TARGET / "app" / "auth.py").read_text(encoding="utf-8")
    if PATCHED_MARKER in source:
        raise SystemExit(
            "demo_target/app/auth.py still contains the fix after reset.\n"
            "The committed baseline appears to be the PATCHED module; the demo\n"
            "needs the vulnerable one. Check what is staged/committed for\n"
            "demo_target/app/auth.py."
        )
    return "confirmed auth.py is the vulnerable baseline"


def clear_runtime_sessions() -> str:
    base_url = agentshield_base_url().rstrip("/")
    try:
        response = httpx.delete(f"{base_url}/api/runtime/sessions", timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return f"AgentShield not reachable at {base_url} ({exc}); nothing to clear"
    return f"cleared {response.json()['cleared']} live session(s)"


def main() -> int:
    print()
    steps = [remove_generated_files()]
    try:
        steps.append(restore_tracked_baseline())
    except SystemExit:
        raise
    if "NOT tracked" in steps[-1]:
        steps.append(fallback_textual_revert())
    steps.append(verify_vulnerable_baseline())
    steps.append(clear_runtime_sessions())

    for step in steps:
        print(f"  {step}")

    result = run_demo_target_tests()
    print(f"  {result.command}: {result.summary}")
    print()

    if not result.passed:
        print("  The baseline is NOT green. Fix demo_target before rehearsing.")
        print(result.tail)
        return 1

    print("  Baseline restored. Ready for another run.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
