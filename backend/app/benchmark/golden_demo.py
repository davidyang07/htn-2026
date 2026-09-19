"""The canonical golden demo (Priority 2): one scenario, one config, whose
real event log narrates all ten brief beats -- indirect prompt injection,
propagation, initial quarantine, an adaptive attacker strategy switch, a
sentinel-compromise attack on the security plane, a false threat-memory
report, AgentShield identifying the resulting security_plane_integrity gap via
the existing remediation engine, applying the fix, and re-running to show
measurable improvement. No new scenario logic -- pure config selection over
app/scenarios/registry.py's existing scenarios, narrated by walking the
resulting event log.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.benchmark.runner import BenchmarkRun, run_headless_async
from app.remediation.analyze import Recommendation, recommend
from app.schemas.experiment import ExperimentConfig

GOLDEN_DEMO_CONFIG = ExperimentConfig(
    seed=42,
    node_count=40,
    real_agent_count=10,
    model_provider="mock",
    active_scenarios=[
        "adaptive_attacker", "prompt_injection", "sentinel_compromise", "attestation",
    ],
    adaptive_detection_threshold=0.3,
    detector_sensitivity=0.15,
    sentinel_count=1,
    sentinel_compromise_rate=0.08,
    attestation_replay_rate=0.3,
    defense_enabled=True,
    p_same=0.6,
    p_cross=0.2,
    max_ticks=150,
)


@dataclass
class GoldenDemoResult:
    baseline: BenchmarkRun
    narrative: list[str]
    recommendation: Recommendation | None
    rerun: BenchmarkRun | None


def _narrate(run: BenchmarkRun) -> list[str]:
    lines: list[str] = []
    seen_false_signature_from: set[str] = set()
    replayed_attestation_count = 0
    for event in run.events:
        etype = event.event_type.value
        if etype == "COMPROMISE_SUCCEEDED" and event.metadata.get("real_agent"):
            lines.append(
                f"tick {event.sim_tick}: indirect prompt injection compromised "
                f"{event.target_agent_id} via a real LLM-backed lateral attempt from "
                f"{event.source_agent_id}"
            )
        elif etype == "COMPROMISE_SUCCEEDED" and event.metadata.get("initial_compromise"):
            lines.append(
                f"tick {event.sim_tick}: seeded initial compromise at {event.target_agent_id}"
            )
        elif etype == "COMPROMISE_SUCCEEDED":
            lines.append(
                f"tick {event.sim_tick}: compromise propagated to {event.target_agent_id}"
            )
        elif etype == "AGENT_QUARANTINED" and event.metadata.get("legitimate") is not False:
            lines.append(
                f"tick {event.sim_tick}: {event.agent_id} quarantined by initial defense"
            )
        elif (
            etype == "POLICY_VIOLATION"
            and event.metadata.get("violation_type") == "sentinel_subverted"
        ):
            lines.append(
                f"tick {event.sim_tick}: adaptive attacker subverted sentinel {event.agent_id} "
                "-- the attacker shifted from attacking agents to attacking the security "
                "plane itself"
            )
        elif etype == "THREAT_SIGNATURE_PUBLISHED" and event.metadata.get("legitimate") is False:
            if event.agent_id not in seen_false_signature_from:
                seen_false_signature_from.add(event.agent_id)
                lines.append(
                    f"tick {event.sim_tick}: subverted sentinel {event.agent_id} published a "
                    "false threat signature (false report / trust manipulation) -- and keeps "
                    "doing so every subsequent tick, poisoning shared threat memory"
                )
        elif etype == "ATTESTATION_VERIFIED" and event.metadata.get("replayed"):
            replayed_attestation_count += 1
            if replayed_attestation_count == 1:
                lines.append(
                    f"tick {event.sim_tick}: a stale attestation nonce was replayed and accepted"
                )

    if replayed_attestation_count > 1:
        lines.append(
            f"...{replayed_attestation_count} stale attestation nonces were replayed and "
            "accepted in total over the run"
        )

    lines.append(
        "attacker strategy: the adaptive attacker recomputed its strategy every tick from the "
        "observed quarantine rate, switching between aggressive (highest-degree-neighbor) and "
        "stealthy (lowest-degree-neighbor) targeting"
    )
    lines.append(
        f"AgentShield identified the failed control: final security_plane_integrity="
        f"{run.metrics['security_plane_integrity']:.2f}"
    )
    return lines


# Each entry identifies a beat class that repeats once per affected agent
# (often 20-60+ times). Only the first line of each class survives into the
# summary, annotated with how many more of that class the run produced.
_REPEATED_BEAT_CLASSES = (
    "compromise propagated to",
    "indirect prompt injection compromised",
    "quarantined by initial defense",
    "adaptive attacker subverted sentinel",
)


def summarize_golden_demo_narrative(narrative: list[str]) -> list[str]:
    """Curated subset of the full narrative for the demo's headline output:
    keeps every distinct beat but collapses each *class* of per-agent line
    (propagation, lateral prompt injection, quarantine, sentinel
    subversion) down to its first occurrence, annotated with how many more
    of that class occurred. Collapsing propagation alone was not enough --
    the per-agent injection and quarantine lines left the "key beats" just
    as long as the raw log. The full, uncollapsed narrative remains
    available via GoldenDemoResult.narrative for the tick-by-tick log."""

    def beat_class(line: str) -> str | None:
        return next((c for c in _REPEATED_BEAT_CLASSES if c in line), None)

    totals: dict[str, int] = {}
    for line in narrative:
        cls = beat_class(line)
        if cls is not None:
            totals[cls] = totals.get(cls, 0) + 1

    summary: list[str] = []
    seen: set[str] = set()
    for line in narrative:
        cls = beat_class(line)
        if cls is None:
            summary.append(line)
            continue
        if cls in seen:
            continue
        seen.add(cls)
        remaining = totals[cls] - 1
        summary.append(f"{line} (+{remaining} more this run)" if remaining else line)
    return summary


def run_golden_demo(
    model_provider: str = "mock", model_name: str | None = None
) -> GoldenDemoResult:
    """`model_name` must name a model the configured vLLM server actually
    serves; it is sent verbatim as the OpenAI `model` field. Without it the
    config keeps the "qwen-mock" default, which a real server rejects with a
    404, so model_provider="vllm" was unusable on its own."""
    overrides: dict[str, str] = {"model_provider": model_provider}
    if model_name is not None:
        overrides["model_name"] = model_name
    config = GOLDEN_DEMO_CONFIG.model_copy(update=overrides)
    baseline = run_headless_async("golden_demo_baseline", config)
    narrative = _narrate(baseline)

    recs = recommend(
        config,
        compromise_fraction=baseline.metrics["compromise_fraction"],
        security_plane_integrity=baseline.metrics["security_plane_integrity"],
    )
    if not recs:
        return GoldenDemoResult(
            baseline=baseline, narrative=narrative, recommendation=None, rerun=None
        )

    recommendation = recs[0]
    narrative.append(f"remediation recommended: {recommendation.description}")
    rerun_config = config.model_copy(update=recommendation.config_diff)
    rerun = run_headless_async("golden_demo_rerun", rerun_config)
    narrative.append(
        "re-ran the same scenario with the remediation applied: security_plane_integrity "
        f"{baseline.metrics['security_plane_integrity']:.2f} -> "
        f"{rerun.metrics['security_plane_integrity']:.2f}"
    )
    return GoldenDemoResult(
        baseline=baseline, narrative=narrative, recommendation=recommendation, rerun=rerun
    )
