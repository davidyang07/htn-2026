"""Sentry: the observability and forensics layer (docs/PROJECT.md §9).

Sentry is the incident record a developer or a judge reads *after* the fact.
It is never on the demo's critical path, and this module is built so that it
cannot become one:

* No `SENTRY_DSN` -> the SDK is never initialized and every helper here is a
  no-op. The application behaves identically.
* `sentry-sdk` not importable at all -> same.
* An initialization failure -> logged once, then the same no-op path.

Additive to, and separate from, the hand-built OTLP/JSON exporter in
`app/telemetry/otel_export.py`, which covers the deterministic simulator.
"""

import json
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)

#: The structured log names the demo's forensics story is told in
#: (docs/PROJECT.md §9). Kept as a frozenset so a typo in a call site fails a
#: test rather than silently producing an unqueryable log.
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

# Telemetry metadata is deny-by-default. These identifiers and measurements
# are enough to correlate the demo without ever accepting arbitrary prompt,
# completion, source-code, resource-content, or credential fields.
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
        "resource_path",
        "requested_files",
        "role",
        "rule",
        "run_id",
        "security_state",
        "session_id",
        "task_id",
        "task_identifier",
        "tests_passed",
        "tainted_artifact_ids",
        "trusted_artifacts",
        "to_worker_id",
        "violation_type",
        "vulnerability_proven",
        "worker_id",
    }
)

_enabled = False


def is_enabled() -> bool:
    return _enabled


def init_sentry(settings: Settings) -> bool:
    """Initialize Sentry if a DSN is configured. Returns whether it is on.

    Safe to call more than once; safe to call with no DSN; safe to call with
    `sentry-sdk` absent from the environment.
    """
    global _enabled

    dsn = settings.optional("sentry_dsn")
    if not dsn:
        logger.info("SENTRY_DSN not set; Sentry disabled for this run")
        _enabled = False
        return False

    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; Sentry disabled")
        _enabled = False
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=settings.sentry_environment,
            # Error monitoring is on by default; these two turn on the other
            # halves the demo's forensics story needs.
            traces_sample_rate=settings.sentry_traces_sample_rate,
            enable_logs=True,
            send_default_pii=False,
            before_send=_before_send,
            before_send_log=_before_send_log,
        )
    except Exception:
        logger.exception("Sentry initialization failed; continuing without it")
        _enabled = False
        return False

    _enabled = True
    logger.info("Sentry enabled (environment=%s)", settings.sentry_environment)
    return True


@contextmanager
def span(op: str, name: str, **data: Any) -> Iterator[None]:
    """One span, or nothing at all.

    Nests under whatever transaction is already current -- including one
    started in the WorkSwarm process and continued here through the
    `sentry-trace`/`baggage` headers the bridge client sends.
    """
    if not _enabled:
        yield
        return

    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover - _enabled implies the import worked
        yield
        return

    try:
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
        try:
            span_context.__exit__(type(error), error, error.__traceback__)
        except Exception:
            logger.debug("Sentry span shutdown failed for %s", name, exc_info=True)
        raise
    else:
        try:
            span_context.__exit__(None, None, None)
        except Exception:
            logger.debug("Sentry span shutdown failed for %s", name, exc_info=True)


def log_event(name: str, message: str, **fields: Any) -> None:
    """Emit one structured log line.

    Always goes to stdlib logging, so the run is legible in a terminal with no
    Sentry configured; additionally goes to Sentry's Logs product when it is.
    """
    if name not in STRUCTURED_LOG_NAMES:
        raise ValueError(f"unknown structured log name {name!r}")

    safe_fields = _safe_fields(fields)
    logger.info("%s | %s", name, safe_fields)

    if not _enabled:
        return

    try:
        from sentry_sdk import logger as sentry_logger

        sentry_logger.info(name, attributes={"event.name": name, **safe_fields})
    except Exception:  # pragma: no cover - telemetry must never break a request
        logger.debug("Sentry log emission failed for %s", name, exc_info=True)


def set_tags(tags: Mapping[str, Any]) -> None:
    if not _enabled:
        return
    try:
        import sentry_sdk

        for key, value in _safe_fields(tags).items():
            sentry_sdk.set_tag(key, value)
    except Exception:  # pragma: no cover
        logger.debug("Sentry tagging failed", exc_info=True)


def _safe_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Return only explicitly approved correlation metadata.

    Sentry log attributes are scalar, so approved collections are recursively
    filtered and serialized. Nested dictionaries do not get to bypass the
    same allowlist as top-level fields.
    """
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


_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "body",
        "completion",
        "content",
        "cookie",
        "data",
        "file_contents",
        "messages",
        "password",
        "prompt",
        "refresh_token",
        "repository_contents",
        "request_body",
        "response_body",
        "secret",
        "source_code",
    }
)


def _before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """Last-line scrubber for SDK integrations outside our helper calls."""
    return _scrub_payload(event)


def _before_send_log(log: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    scrubbed = _scrub_payload(log)
    body = log.get("body")
    if body in STRUCTURED_LOG_NAMES:
        scrubbed["body"] = body
    return scrubbed


def _scrub_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        scrubbed = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if _is_sensitive_key(normalized):
                scrubbed[key] = "[Filtered]"
            else:
                scrubbed[key] = _scrub_payload(item)
        return scrubbed
    if isinstance(value, list):
        return [_scrub_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_payload(item) for item in value)
    return value


def _is_sensitive_key(key: str) -> bool:
    return key in _SENSITIVE_KEYS or key.endswith(
        ("_api_key", "_authorization", "_password", "_secret", "_token")
    )
