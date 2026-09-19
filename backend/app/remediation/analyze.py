"""Deterministic, rule-based remediation engine (docs/PLAN.md §7).

Every recommendation targets a config field with a *causally verified*
effect on this codebase's implemented scenarios/detection:
`detector_sensitivity` and `defense_enabled` are wired into
app/security/detection.py's quarantine behavior; `sentinel_count` is wired
into the same module's compromised-sentinel detection-suppression
(app/security/detection.py::_suppressed_by_compromised_sentinels,
docs/PLAN.md §5) -- spreading monitoring across more sentinels shrinks the
fraction of agents a single subverted sentinel can suppress, a claim
covered by test_sentinel_compromise.py and re-verified for the
recommendation itself in test_remediation.py. Other structural levers
(credential consolidation) remain deliberately NOT recommended: they have
no causal effect on any implemented scenario yet, and recommending them
would be an unverifiable, fabricated "fix" that re-running the experiment
could not actually confirm. Each recommendation's `config_diff` is directly
usable as a `POST /api/experiments` body field for re-testing -- scoring
the fix reuses the existing comparison flow, no new re-test machinery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.experiment import ExperimentConfig

HIGH_COMPROMISE_THRESHOLD = 0.3
SENSITIVITY_INCREMENT = 0.2
MAX_SENTINEL_COUNT = 5


@dataclass
class Recommendation:
    description: str
    config_diff: dict[str, Any] = field(default_factory=dict)


def recommend(
    config: ExperimentConfig,
    compromise_fraction: float,
    security_plane_integrity: float = 1.0,
) -> list[Recommendation]:
    if security_plane_integrity < 1.0 and 0 < config.sentinel_count < MAX_SENTINEL_COUNT:
        new_count = min(MAX_SENTINEL_COUNT, config.sentinel_count + 1)
        return [
            Recommendation(
                description=(
                    f"Security-plane integrity is {security_plane_integrity:.0%} -- at least "
                    f"one sentinel is compromised. Raise sentinel_count from "
                    f"{config.sentinel_count} to {new_count} to shrink the fraction of agents "
                    "a single subverted sentinel's detection suppression can reach."
                ),
                config_diff={"sentinel_count": new_count},
            )
        ]

    if compromise_fraction <= HIGH_COMPROMISE_THRESHOLD:
        return []

    if not config.defense_enabled:
        return [
            Recommendation(
                description=(
                    f"{compromise_fraction:.0%} of agents are compromised and quarantine "
                    "defense is disabled -- enable it."
                ),
                config_diff={"defense_enabled": True},
            )
        ]

    if config.detector_sensitivity < 1.0:
        new_sensitivity = round(min(1.0, config.detector_sensitivity + SENSITIVITY_INCREMENT), 2)
        return [
            Recommendation(
                description=(
                    f"{compromise_fraction:.0%} of agents are compromised despite defense "
                    f"being enabled -- raise detector_sensitivity from "
                    f"{config.detector_sensitivity} to {new_sensitivity}."
                ),
                config_diff={"detector_sensitivity": new_sensitivity},
            )
        ]

    return []
