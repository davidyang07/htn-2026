"""Truth conditions for the Live Swarm Demo's recovery claim."""

from __future__ import annotations


def recovery_was_demonstrated(
    *, approved: bool, tests_passed: bool, vulnerability_proven: bool, quarantined: bool
) -> bool:
    """A successful patch alone is not evidence that swarm recovery occurred."""
    return approved and tests_passed and vulnerability_proven and quarantined
