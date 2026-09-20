"""Applying the Developer worker's patch, inside the sandbox and nowhere else.

Two hard rules, both enforced here rather than asked for in a prompt:

* **A worker must not write outside `demo_target/`** (docs/DEMO.md §5.6). Every
  write resolves its path and refuses anything that lands outside the sandbox
  root, including through `..` and symlinks.
* **A worker must not write into `demo_target/secrets/`.** The protected
  directory is protected in both directions: a compromised worker cannot read
  it, and cannot overwrite it either.

The patch itself is real: a real edit to `demo_target/app/auth.py` and a real
new test file, both verified afterwards by a real `pytest` run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from workswarm.config import SANDBOX_ROOT

PROTECTED_DIRNAME = "secrets"


class SandboxViolation(Exception):
    """A write was attempted outside the sandbox, or into the protected dir."""


@dataclass(frozen=True)
class PatchResult:
    files_written: tuple[str, ...]
    explanation: str


def resolve_in_sandbox(relative_path: str) -> Path:
    """The absolute path a sandbox-relative write targets, or an exception."""
    candidate = relative_path.strip().replace("\\", "/")
    if not candidate:
        raise SandboxViolation("empty write path")

    # Accept both sandbox-relative ("app/auth.py") and repo-relative
    # ("demo_target/app/auth.py") spellings. A bare "demo_target" names the
    # sandbox root, which is a directory, not a file anyone can write.
    root_name = SANDBOX_ROOT.name
    if candidate == root_name or candidate == f"{root_name}/":
        raise SandboxViolation("cannot write to the sandbox root itself")
    prefix = f"{root_name}/"
    if candidate.startswith(prefix):
        candidate = candidate[len(prefix) :]

    root = SANDBOX_ROOT.resolve()
    target = (root / candidate).resolve()

    if not target.is_relative_to(root):
        raise SandboxViolation(f"{relative_path!r} resolves outside {root}")

    relative_parts = target.relative_to(root).parts
    if relative_parts and relative_parts[0].lower() == PROTECTED_DIRNAME:
        raise SandboxViolation(
            f"{relative_path!r} targets the protected directory; writes are refused"
        )
    if not relative_parts:
        raise SandboxViolation("cannot write to the sandbox root itself")

    return target


def write_in_sandbox(relative_path: str, content: str) -> str:
    """Write one file inside the sandbox. Returns the repo-relative path."""
    target = resolve_in_sandbox(relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"demo_target/{target.relative_to(SANDBOX_ROOT.resolve()).as_posix()}"


def read_in_sandbox(relative_path: str) -> str:
    return resolve_in_sandbox(relative_path).read_text(encoding="utf-8")


# --- the deterministic fix -----------------------------------------------
#
# Used when no model is configured. It is a *real* transformation of the
# module's current source, not a stored blob swapped in: it finds the block
# that parses `expires_at` and discards it, and replaces it with one that
# enforces the expiry. If the source has already been patched, it says so
# rather than pretending to have done work.

VULNERABLE_BLOCK = """    try:
        int(encoded_expiry)
    except ValueError as exc:
        raise AuthError("malformed token") from exc

    return user_id
"""

PATCHED_BLOCK = """    try:
        expires_at = int(encoded_expiry)
    except ValueError as exc:
        raise AuthError("malformed token") from exc

    # A signed token whose expires_at has passed must be rejected: a signature
    # check alone makes every token ever issued valid forever, which turns a
    # single leaked token into permanent access.
    current_time = time.time() if now is None else now
    if current_time >= expires_at:
        raise AuthError("token expired")

    return user_id
"""

REGRESSION_TEST_SOURCE = '''"""Regression coverage for the session-expiry vulnerability.

Fails against the unpatched `verify_token()`, which checks the signature and
ignores `expires_at`; passes once expiry is enforced.
"""

import pytest

from app.auth import AuthError, issue_token, verify_token

SIGNING_KEY = "demo-service-signing-key"
NOW = 1_700_000_000.0


def test_expired_token_is_rejected():
    token = issue_token("alice", SIGNING_KEY, ttl_seconds=900, now=NOW)
    with pytest.raises(AuthError):
        verify_token(token, SIGNING_KEY, now=NOW + 901)


def test_token_is_still_accepted_before_it_expires():
    token = issue_token("alice", SIGNING_KEY, ttl_seconds=900, now=NOW)
    assert verify_token(token, SIGNING_KEY, now=NOW + 899) == "alice"
'''


def deterministic_auth_patch() -> tuple[str, str]:
    """Return the patched `auth.py` source and the regression test source.

    Raises if the module is not in the state the patch expects, rather than
    silently producing something that does not compile.
    """
    source = read_in_sandbox("app/auth.py")
    if VULNERABLE_BLOCK not in source:
        if "token expired" in source:
            raise SandboxViolation(
                "demo_target/app/auth.py is already patched; reset with "
                "`python workswarm/reset_demo.py` before running the demo"
            )
        raise SandboxViolation(
            "demo_target/app/auth.py is not in the shape this patch expects"
        )
    return source.replace(VULNERABLE_BLOCK, PATCHED_BLOCK), REGRESSION_TEST_SOURCE
