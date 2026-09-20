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
        for key, value in data.items():
            current.set_data(key, value)
        yield


def log_event(name: str, message: str, **fields: Any) -> None:
    """Emit one structured log line.

    Always goes to stdlib logging, so the run is legible in a terminal with no
    Sentry configured; additionally goes to Sentry's Logs product when it is.
    """
    if name not in STRUCTURED_LOG_NAMES:
        raise ValueError(f"unknown structured log name {name!r}")

    logger.info("%s | %s | %s", name, message, fields)

    if not _enabled:
        return

    try:
        import sentry_sdk

        sentry_sdk.logger.info(message, attributes={"event.name": name, **_scalars(fields)})
    except Exception:  # pragma: no cover - telemetry must never break a request
        logger.debug("Sentry log emission failed for %s", name, exc_info=True)


def set_tags(tags: Mapping[str, Any]) -> None:
    if not _enabled:
        return
    try:
        import sentry_sdk

        for key, value in tags.items():
            sentry_sdk.set_tag(key, value)
    except Exception:  # pragma: no cover
        logger.debug("Sentry tagging failed", exc_info=True)


def _scalars(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Sentry log attributes take scalars. Anything else is stringified here
    rather than dropped, so a list of tainted artifact ids still shows up."""
    flattened: dict[str, Any] = {}
    for key, value in fields.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            flattened[key] = value
        else:
            flattened[key] = str(value)
    return flattened
