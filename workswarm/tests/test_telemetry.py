"""Safety contract for WorkSwarm's optional Sentry integration."""

from unittest.mock import Mock

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


def test_workflow_logs_scrub_flat_and_nested_sensitive_fields(monkeypatch):
    from sentry_sdk import logger as sentry_logger

    sdk_logger = Mock()
    monkeypatch.setattr(telemetry, "_enabled", True)
    monkeypatch.setattr(sentry_logger, "info", sdk_logger.info)

    telemetry.log_event(
        "swarm.task_reassigned",
        "free-form task text is not sent",
        run_id="run-123",
        worker_id="replacement-researcher",
        resource_path="demo_target/app/auth.py",
        api_key="sk-secret",
        prompt="arbitrary prompt",
        replacement_relationship={
            "from_worker_id": "security-researcher",
            "to_worker_id": "replacement-researcher",
            "authorization": "Bearer nested-secret",
            "completion": "arbitrary completion",
        },
    )

    sdk_logger.info.assert_called_once_with(
        "swarm.task_reassigned",
        attributes={
            "event.name": "swarm.task_reassigned",
            "run_id": "run-123",
            "worker_id": "replacement-researcher",
            "resource_path": "demo_target/app/auth.py",
            "replacement_relationship": (
                '{"from_worker_id":"security-researcher",'
                '"to_worker_id":"replacement-researcher"}'
            ),
        },
    )
