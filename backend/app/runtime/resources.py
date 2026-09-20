"""Fetching an allowed sandbox resource -- the *second* half of the
enforcement point (docs/ARCHITECTURE.md §2).

The corollary that constrains every implementation choice in the live runtime:

    no code path may read a protected file on behalf of a worker before the
    policy decision returns.

So this module never takes a raw worker-supplied string. It takes a path the
policy has already normalized, and re-evaluates the policy over it anyway
before touching the filesystem. Belt and braces: the fetch half cannot be
reached with a protected path even by a caller that forgot to check, and a
future refactor that reorders the route handler fails loudly here instead of
quietly reading the secret.
"""

from pathlib import Path

from app.runtime.policy import SANDBOX_ROOT, evaluate

#: backend/app/runtime/resources.py -> backend/app/runtime -> backend/app ->
#: backend -> the repository root, which is what sandbox paths are relative to.
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Refuse to hand a worker an unbounded blob. The demo's documents are a few
#: kilobytes; anything larger is a mistake, not a resource request.
MAX_RESOURCE_BYTES = 256 * 1024


class ResourceAccessError(Exception):
    """The resource could not be served. Never raised for a denied path --
    a denial is a Decision, not an exception."""


class PolicyBypassError(Exception):
    """A caller tried to fetch a path the policy denies.

    This is a programming error in AgentShield itself, not an attack by a
    worker: the worker's request is supposed to have been answered with a
    denial long before anything reached this module.
    """


def read_sandbox_resource(resource_path: str, *, root: Path | None = None) -> str:
    """Return the text of an allowed sandbox resource.

    Raises :class:`PolicyBypassError` if the policy denies ``resource_path``,
    and :class:`ResourceAccessError` if an allowed path cannot be read.
    """
    decision = evaluate(resource_path)
    if not decision.allowed or decision.normalized_path is None:
        raise PolicyBypassError(
            f"read_sandbox_resource called with a denied path ({decision.rule})"
        )

    base = (root or REPO_ROOT).resolve()
    sandbox = (base / SANDBOX_ROOT).resolve()
    target = (base / decision.normalized_path).resolve()

    # Re-check the fully resolved target. A symlink beneath an allowed path
    # can otherwise jump to backend/ (still inside the repository) or back
    # into demo_target/secrets/ after the raw request already passed policy.
    if not sandbox.is_relative_to(base) or not target.is_relative_to(sandbox):
        raise PolicyBypassError("resolved resource escapes the sandbox root")

    resolved_relative = target.relative_to(base).as_posix()
    resolved_decision = evaluate(resolved_relative)
    if not resolved_decision.allowed:
        raise PolicyBypassError(
            f"resolved resource is denied by policy ({resolved_decision.rule})"
        )

    if not target.is_file():
        raise ResourceAccessError(f"{decision.normalized_path} is not a readable file")

    size = target.stat().st_size
    if size > MAX_RESOURCE_BYTES:
        raise ResourceAccessError(
            f"{decision.normalized_path} is {size} bytes; the limit is {MAX_RESOURCE_BYTES}"
        )

    try:
        return target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ResourceAccessError(str(exc)) from exc
