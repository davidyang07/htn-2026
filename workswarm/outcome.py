"""Truth conditions for the Live Swarm Demo's recovery claim."""

from __future__ import annotations

from workswarm.config import policy_request_paths


def recovery_was_demonstrated(
    *, approved: bool, tests_passed: bool, vulnerability_proven: bool, quarantined: bool
) -> bool:
    """A successful patch alone is not evidence that swarm recovery occurred."""
    return approved and tests_passed and vulnerability_proven and quarantined


def denied_worker_requests(requested: list[str], denied: list[str]) -> list[str]:
    """Return denied paths that originated in the worker's structured output."""
    denied_set = set(denied)
    return [path for path in policy_request_paths(requested) if path in denied_set]
