"""Safety contract for WorkSwarm's optional Sentry integration."""

from workswarm import telemetry


def test_workflow_telemetry_is_a_no_op_without_a_dsn(monkeypatch):
    monkeypatch.setattr(telemetry, "sentry_dsn", lambda: None)

    assert telemetry.init() is False
    assert telemetry.is_enabled() is False

    with telemetry.transaction("agentshield.demo"):
        with telemetry.span(
            "workswarm.repo_analyst",
            "repo analyst",
            worker_id="repo-analyst",
        ):
            pass

    manual = telemetry.ManualSpan("workswarm.analysis", "analysis")
    manual.open()
    manual.close()
    manual.close()
    telemetry.log_event(
        "security.tool_denied",
        "denied",
        worker_id="security-researcher",
    )
