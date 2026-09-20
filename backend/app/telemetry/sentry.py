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
        "decision",
        "event_type",
        "exit_code",
        "fail_closed",
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
        "replaces",
        "replacement_worker_id",
        "resource_path",
        "role",
        "rule",
        "run_id",
        "security_state",
        "session_id",
        "task_id",
        "task_identifier",
        "tests_passed",
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

    with sentry_sdk.start_span(op=op, name=name) as current:
        for key, value in _safe_fields(data).items():
            current.set_data(key, value)
        yield


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
        import sentry_sdk

        sentry_sdk.logger.info(name, attributes={"event.name": name, **safe_fields})
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
    """Return only explicitly approved scalar correlation metadata."""
    safe: dict[str, Any] = {}
    for key, value in fields.items():
        if key in SAFE_FIELD_NAMES and (
            value is None or isinstance(value, (str, int, float, bool))
        ):
            safe[key] = value
    return safe
