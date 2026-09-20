"""Safety contract for WorkSwarm's optional Sentry integration."""

from unittest.mock import Mock

import pytest

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


def test_workflow_structured_log_names_cover_the_demo_story():
    assert telemetry.STRUCTURED_LOG_NAMES == {
        "security.policy_violation",
        "security.tool_denied",
        "security.agent_quarantined",
        "swarm.task_reassigned",
        "swarm.replacement_started",
        "developer.regression_failed",
        "developer.patch_applied",
        "swarm.tests_passed",
        "swarm.recovery_complete",
    }


def test_workflow_sdk_egress_scrubber_filters_nested_payloads():
    scrubbed = telemetry._before_send(
        {
            "request": {
                "headers": {"Authorization": "Bearer secret"},
                "data": {"prompt": "full prompt", "api_key": "sk-secret"},
            },
            "tags": {"run_id": "run-123"},
        },
        {},
    )

    assert scrubbed == {
        "request": {
            "headers": {"Authorization": "[Filtered]"},
            "data": "[Filtered]",
        },
        "tags": {"run_id": "run-123"},
    }


def test_workflow_trace_helpers_isolate_sdk_failures(monkeypatch):
    class BrokenOnExit:
        def __enter__(self):
            return Mock()

        def __exit__(self, *_exc_info):
            raise ConnectionError("transport unavailable")

    monkeypatch.setattr(telemetry, "_enabled", True)
    monkeypatch.setattr(
        "sentry_sdk.start_transaction",
        lambda **_kwargs: BrokenOnExit(),
    )
    monkeypatch.setattr("sentry_sdk.start_span", lambda **_kwargs: BrokenOnExit())

    with telemetry.transaction("agentshield.demo"):
        with telemetry.span("workswarm.repo_analyst", "repo analyst"):
            application_result = "preserved"

    manual = telemetry.ManualSpan("workswarm.analysis", "analysis")
    manual.open()
    manual.close()
    manual.close()

    assert application_result == "preserved"


def test_trace_helpers_do_not_swallow_application_exceptions(monkeypatch):
    class HealthyContext:
        def __enter__(self):
            return Mock()

        def __exit__(self, *_exc_info):
            return True

    monkeypatch.setattr(telemetry, "_enabled", True)
    monkeypatch.setattr(
        "sentry_sdk.start_transaction",
        lambda **_kwargs: HealthyContext(),
    )

    with pytest.raises(RuntimeError, match="application failed"):
        with telemetry.transaction("agentshield.demo"):
            raise RuntimeError("application failed")
