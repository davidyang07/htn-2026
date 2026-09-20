"""Provider selection for the Replacement Researcher.

This module contains no network or policy code.  It only turns an already
verified RunPod candidate and the normal WorkSwarm model into an explicit,
truthful route decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from workswarm.config import ModelConfig, NO_MODEL


@dataclass(frozen=True)
class ReplacementProviderSelection:
    """The model route selected for the replacement worker."""

    model: ModelConfig
    route: str
    fallback_used: bool
    reason: str


def select_replacement_provider(
    *,
    sponsor: ModelConfig,
    runpod: ModelConfig | None,
    runpod_healthy: bool,
    reason: str = "",
) -> ReplacementProviderSelection:
    """Prefer a verified RunPod model and otherwise preserve the P0 route."""
    if runpod is not None and runpod.configured and runpod_healthy:
        return ReplacementProviderSelection(
            model=runpod,
            route="runpod",
            fallback_used=False,
            reason=reason or "RunPod endpoint verified",
        )

    fallback_reason = reason or (
        "RunPod endpoint is not configured"
        if runpod is None or not runpod.configured
        else "RunPod endpoint is unhealthy"
    )
    if sponsor.configured:
        return ReplacementProviderSelection(
            model=sponsor,
            route="sponsor_fallback",
            fallback_used=True,
            reason=fallback_reason,
        )

    return ReplacementProviderSelection(
        model=NO_MODEL,
        route="deterministic_fallback",
        fallback_used=True,
        reason=fallback_reason,
    )
