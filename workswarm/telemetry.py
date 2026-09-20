"""Sentry on the workflow side of the demo (docs/MVP_PLAN.md P0.13).

The SwarmFlow owns the trace: it starts the ``agentshield.demo`` transaction
and opens a span per workflow step. `agentshield_client.py` puts the current
`sentry-trace`/`baggage` headers on every HTTP call, so AgentShield's own
`agentshield.policy_check`, `agentshield.quarantine` and `task.reassignment`
spans land inside the same trace as children of the step that caused them.

Optional throughout. No `SENTRY_DSN`, or no `sentry-sdk` installed, means every
helper here is a no-op and the demo runs identically.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from workswarm.config import sentry_dsn

logger = logging.getLogger(__name__)

_enabled = False

SAFE_FIELD_NAMES = frozenset(
    {
        "artifact_id",
        "attack_detected",
        "context_artifact_ids",
        "decision",
        "event_type",
        "exit_code",
        "fail_closed",
        "files_written",
        "from_worker_id",
        "latency_ms",
        "model",
        "model_backed",
        "model_latency_ms",
        "phase",
        "policy_result",
        "provider",
        "pytest_exit_code",
        "quarantined_worker",
        "replacement_relationship",
        "replaces",
        "replacement_worker_id",
        "requested_files",
        "resource_path",
        "role",
        "rule",
        "run_id",
        "security_state",
        "session_id",
        "tainted_artifact_ids",
        "task_id",
        "task_identifier",
        "tests_passed",
        "to_worker_id",
        "trusted_artifacts",
        "violation_type",
        "vulnerability_proven",
        "worker_id",
    }
)

STRUCTURED_LOG_NAMES = frozenset(
    {
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
)


def is_enabled() -> bool:
    return _enabled


def init(environment: str = "local") -> bool:
    global _enabled
    dsn = sentry_dsn()
    if not dsn:
        logger.info("SENTRY_DSN not set; the workflow will not emit telemetry")
        _enabled = False
        return False

    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=1.0,
            enable_logs=True,
            send_default_pii=False,
        )
    except Exception:
        logger.warning("Sentry initialization failed; continuing without it", exc_info=True)
        _enabled = False
        return False

    _enabled = True
    return True


@contextmanager
def transaction(name: str, op: str = "swarm.run") -> Iterator[None]:
    """The whole swarm run: one trace for the judge to read afterwards."""
    if not _enabled:
        yield
        return

    try:
        import sentry_sdk

        transaction_context = sentry_sdk.start_transaction(op=op, name=name)
        transaction_context.__enter__()
    except Exception:
        logger.debug("Sentry transaction startup failed for %s", name, exc_info=True)
        yield
        return

    try:
        yield
    except BaseException as error:
        _close_context(transaction_context, name, error)
        raise
    else:
        _close_context(transaction_context, name)


@contextmanager
def span(op: str, name: str, **data: Any) -> Iterator[None]:
    if not _enabled:
        yield
        return

    try:
        import sentry_sdk

        span_context = sentry_sdk.start_span(op=op, name=name)
        current = span_context.__enter__()
    except Exception:
        logger.debug("Sentry span startup failed for %s", name, exc_info=True)
        yield
        return

    try:
        for key, value in _safe_fields(data).items():
            try:
                current.set_data(key, value)
            except Exception:
                logger.debug("Sentry span metadata failed for %s", name, exc_info=True)
        yield
    except BaseException as error:
        _close_context(span_context, name, error)
        raise
    else:
        _close_context(span_context, name)


def _close_context(context: Any, name: str, error: BaseException | None = None) -> None:
    try:
        if error is None:
            context.__exit__(None, None, None)
        else:
            context.__exit__(type(error), error, error.__traceback__)
    except Exception:
        logger.debug("Sentry context shutdown failed for %s", name, exc_info=True)


class ManualSpan:
    """A span that starts in one workflow node and ends in another.

    The analysis phase spans two components that the graph runs concurrently,
    so it cannot be a `with` block inside either of them. Entering and exiting
    explicitly is the honest way to express that; it is a no-op when Sentry is
    off, and `close()` is safe to call twice.
    """

    def __init__(self, op: str, name: str) -> None:
        self._op = op
        self._name = name
        self._cm: Any = None

    def open(self) -> None:
        if not _enabled or self._cm is not None:
            return
        try:
            import sentry_sdk

            self._cm = sentry_sdk.start_span(op=self._op, name=self._name)
            self._cm.__enter__()
        except Exception:  # pragma: no cover - telemetry must never break a run
            logger.debug("Sentry manual span startup failed for %s", self._name, exc_info=True)
            self._cm = None

    def close(self) -> None:
        if self._cm is None:
            return
        try:
            self._cm.__exit__(None, None, None)
        except Exception:  # pragma: no cover
            logger.debug("Sentry manual span shutdown failed for %s", self._name, exc_info=True)
        finally:
            self._cm = None


def log_event(name: str, message: str, **fields: Any) -> None:
    """Structured log, always to stdlib logging and additionally to Sentry."""
    if name not in STRUCTURED_LOG_NAMES:
        raise ValueError(f"unknown structured log name {name!r}")

    safe_fields = _safe_fields(fields)
    logger.info("%s | %s", name, safe_fields)
    if not _enabled:
        return
    try:
        from sentry_sdk import logger as sentry_logger

        sentry_logger.info(name, attributes={"event.name": name, **safe_fields})
    except Exception:  # pragma: no cover
        logger.debug("Sentry log emission failed for %s", name, exc_info=True)


def _safe_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in SAFE_FIELD_NAMES:
            continue
        scrubbed = _safe_value(value)
        if scrubbed is not _DROP:
            safe[key] = scrubbed
    return safe


_DROP = object()


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        nested = {
            key: scrubbed
            for key, item in value.items()
            if key in SAFE_FIELD_NAMES
            and (scrubbed := _safe_value(item)) is not _DROP
        }
        return json.dumps(nested, sort_keys=True, separators=(",", ":"))
    if isinstance(value, (list, tuple, set, frozenset)):
        nested_values = []
        for item in value:
            if isinstance(item, Mapping):
                filtered = {
                    key: nested
                    for key, nested_item in item.items()
                    if key in SAFE_FIELD_NAMES
                    and (nested := _safe_value(nested_item)) is not _DROP
                }
                nested_values.append(filtered)
            else:
                scrubbed = _safe_value(item)
                if scrubbed is not _DROP:
                    nested_values.append(scrubbed)
        return json.dumps(nested_values, sort_keys=True, separators=(",", ":"))
    return _DROP
