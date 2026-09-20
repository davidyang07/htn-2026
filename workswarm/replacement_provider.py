"""Provider selection for the Replacement Researcher.

This module contains no network or policy code.  It only turns an already
verified RunPod candidate and the normal WorkSwarm model into an explicit,
truthful route decision.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from workswarm.config import NO_MODEL, ModelConfig
from workswarm.runpod_verify import RunPodVerifier, VerificationReport


@dataclass(frozen=True)
class ReplacementProviderSelection:
    """The model route selected for the replacement worker."""

    model: ModelConfig
    route: str
    fallback_used: bool
    reason: str


@dataclass(frozen=True)
class ReplacementProviderResolution:
    """Selection plus any RunPod evidence gathered while making it."""

    selection: ReplacementProviderSelection
    verification: VerificationReport | None


@dataclass(frozen=True)
class ProviderUse:
    """What actually answered one Replacement Researcher invocation."""

    model: ModelConfig
    route: str
    fallback_used: bool
    reason: str


class ReplacementFailover:
    """Try verified RunPod once, then invoke the normal P0 worker."""

    def __init__(self, runpod: ModelConfig, fallback: ModelConfig) -> None:
        self.runpod = runpod
        self.fallback = fallback
        self.last_use: ProviderUse | None = None

    async def invoke(
        self,
        primary_call: Callable[[], Awaitable[Any]],
        fallback_call: Callable[[], Awaitable[Any]],
    ) -> Any:
        try:
            result = await primary_call()
        except Exception as exc:
            route = "sponsor_fallback" if self.fallback.configured else "deterministic_fallback"
            result = await fallback_call()
            self.last_use = ProviderUse(
                model=self.fallback,
                route=route,
                fallback_used=True,
                reason=f"RunPod invocation failed ({type(exc).__name__})",
            )
            return result

        self.last_use = ProviderUse(
            model=self.runpod,
            route="runpod",
            fallback_used=False,
            reason="RunPod invocation succeeded",
        )
        return result


def provider_use_from_selection(selection: ReplacementProviderSelection) -> ProviderUse:
    """Turn a preflight selection into the same shape as runtime failover."""
    return ProviderUse(
        model=selection.model,
        route=selection.route,
        fallback_used=selection.fallback_used,
        reason=selection.reason,
    )


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


def _failure_reason(report: VerificationReport) -> str:
    probes = [report.health]
    if report.models is not None:
        probes.append(report.models.probe)
    if report.first_completion is not None:
        probes.append(report.first_completion.probe)
    if report.warm_completion is not None:
        probes.append(report.warm_completion.probe)
    failed = next((probe for probe in probes if not probe.ok), report.health)
    return f"RunPod {failed.name} check failed: {failed.detail}"


def select_verified_replacement(
    *,
    sponsor: ModelConfig,
    runpod: ModelConfig | None,
    verifier_factory: Callable[[ModelConfig], RunPodVerifier] = RunPodVerifier,
) -> ReplacementProviderResolution:
    """Verify RunPod and select it only when every required check succeeds."""
    if runpod is None or not runpod.configured:
        return ReplacementProviderResolution(
            selection=select_replacement_provider(
                sponsor=sponsor,
                runpod=runpod,
                runpod_healthy=False,
                reason="RunPod endpoint is not configured",
            ),
            verification=None,
        )

    verifier: RunPodVerifier | None = None
    try:
        verifier = verifier_factory(runpod)
        report = verifier.verify()
    except Exception as exc:
        return ReplacementProviderResolution(
            selection=select_replacement_provider(
                sponsor=sponsor,
                runpod=runpod,
                runpod_healthy=False,
                reason=f"RunPod verification failed ({type(exc).__name__})",
            ),
            verification=None,
        )
    finally:
        if verifier is not None:
            verifier.close()

    return ReplacementProviderResolution(
        selection=select_replacement_provider(
            sponsor=sponsor,
            runpod=runpod,
            runpod_healthy=report.ready,
            reason="RunPod endpoint verified" if report.ready else _failure_reason(report),
        ),
        verification=report,
    )
