import re

from app.benchmark.golden_demo import run_golden_demo, summarize_golden_demo_narrative


def test_golden_demo_is_deterministic():
    result1 = run_golden_demo()
    result2 = run_golden_demo()
    assert result1.baseline.metrics == result2.baseline.metrics
    assert result1.narrative == result2.narrative


def test_golden_demo_produces_all_narrative_beats():
    result = run_golden_demo()
    required_substrings = [
        "prompt injection",  # beat 1/2: indirect prompt injection + propagation
        "quarantined",  # beat 3: initial defense detects/quarantines
        "adaptive attacker",  # beat 4: strategy switch
        "sentinel",  # beat 5: attacker targets the security plane
        "false threat signature",  # beat 6: false report / trust manipulation
        "security_plane_integrity",  # beat 7: AgentShield identifies the failed control
        "remediation recommended",  # beat 8: remediation applied
        "re-ran",  # beat 9: same scenario re-run
    ]
    joined = "\n".join(result.narrative)
    for substring in required_substrings:
        assert substring in joined, f"missing beat evidence: {substring!r}\n\n{joined}"


def test_golden_demo_shows_measurable_resilience_improvement():
    result = run_golden_demo()
    assert result.recommendation is not None
    assert result.rerun is not None
    # security_plane_integrity is the metric the recommendation directly
    # targets (docs/PLAN.md §7); retained_utility is the downstream effect
    # of more agents keeping a healthy sentinel watching them.
    assert (
        result.rerun.metrics["security_plane_integrity"]
        >= result.baseline.metrics["security_plane_integrity"]
    )
    assert (
        result.rerun.metrics["retained_utility"] >= result.baseline.metrics["retained_utility"]
    )


def test_summarize_golden_demo_narrative_collapses_repeated_propagation_lines():
    narrative = [
        "tick 1: seeded initial compromise at agent-000",
        "tick 2: compromise propagated to agent-001",
        "tick 3: compromise propagated to agent-002",
        "tick 4: compromise propagated to agent-003",
        "tick 5: agent-004 quarantined by initial defense",
    ]
    summary = summarize_golden_demo_narrative(narrative)
    propagated_lines = [line for line in summary if "compromise propagated to" in line]
    assert len(propagated_lines) <= 1
    assert "seeded initial compromise at agent-000" in "\n".join(summary)
    assert "quarantined by initial defense" in "\n".join(summary)


def test_summarize_golden_demo_narrative_preserves_order_and_all_required_beats():
    result = run_golden_demo()
    summary = summarize_golden_demo_narrative(result.narrative)
    required_substrings = [
        "prompt injection",
        "quarantined",
        "adaptive attacker",
        "sentinel",
        "false threat signature",
        "security_plane_integrity",
        "remediation recommended",
        "re-ran",
    ]
    joined = "\n".join(summary)
    for substring in required_substrings:
        assert substring in joined, f"missing beat evidence in summary: {substring!r}"
    # order-preserving: summary is a subsequence of the full narrative, once
    # the "(+N more this run)" collapse annotations are stripped back off.
    it = iter(result.narrative)
    assert all(_strip_collapse_note(line) in it for line in summary)


def _strip_collapse_note(line: str) -> str:
    return re.sub(r" \(\+\d+ more this run\)$", "", line)


def test_summary_keeps_at_most_one_line_per_repeated_beat_class():
    # The point of the summary is that it is materially shorter than the raw
    # log: collapsing propagation alone still left one line per agent for
    # lateral injection and quarantine.
    result = run_golden_demo()
    summary = summarize_golden_demo_narrative(result.narrative)
    for beat_class in (
        "compromise propagated to",
        "indirect prompt injection compromised",
        "quarantined by initial defense",
        "adaptive attacker subverted sentinel",
    ):
        matching = [line for line in summary if beat_class in line]
        assert len(matching) <= 1, f"{beat_class!r} was not collapsed: {matching}"
    assert len(summary) < len(result.narrative)
    assert len(summary) <= 12, f"summary is still {len(summary)} lines:\n" + "\n".join(summary)


def test_summary_reports_how_many_repeats_it_collapsed():
    narrative = [
        "tick 2: compromise propagated to agent-001",
        "tick 3: compromise propagated to agent-002",
        "tick 4: compromise propagated to agent-003",
        "tick 5: agent-004 quarantined by initial defense",
    ]
    summary = summarize_golden_demo_narrative(narrative)
    assert summary == [
        "tick 2: compromise propagated to agent-001 (+2 more this run)",
        "tick 5: agent-004 quarantined by initial defense",
    ]


def test_model_name_override_reaches_the_config():
    """model_provider="vllm" alone left model_name at the "qwen-mock" default,
    which a real vLLM server rejects with a 404 -- the documented
    --model-provider vllm invocation could not work without this."""
    result = run_golden_demo(model_provider="mock", model_name="Qwen/Qwen2.5-7B-Instruct")
    assert result.baseline.config.model_name == "Qwen/Qwen2.5-7B-Instruct"


def test_model_name_defaults_are_left_untouched_when_not_passed():
    result = run_golden_demo(model_provider="mock")
    assert result.baseline.config.model_name == "qwen-mock"
