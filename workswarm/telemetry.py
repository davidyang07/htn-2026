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

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from workswarm.config import sentry_dsn

logger = logging.getLogger(__name__)

_enabled = False


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
    import sentry_sdk

    with sentry_sdk.start_transaction(op=op, name=name):
        yield


@contextmanager
def span(op: str, name: str, **data: Any) -> Iterator[None]:
    if not _enabled:
        yield
        return
    import sentry_sdk

    with sentry_sdk.start_span(op=op, name=name) as current:
        for key, value in data.items():
            current.set_data(key, value)
        yield


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
        import sentry_sdk

        self._cm = sentry_sdk.start_span(op=self._op, name=self._name)
        try:
            self._cm.__enter__()
        except Exception:  # pragma: no cover - telemetry must never break a run
            self._cm = None

    def close(self) -> None:
        if self._cm is None:
            return
        try:
            self._cm.__exit__(None, None, None)
        except Exception:  # pragma: no cover
            pass
        finally:
            self._cm = None


def log_event(name: str, message: str, **fields: Any) -> None:
    """Structured log, always to stdlib logging and additionally to Sentry."""
    logger.info("%s | %s | %s", name, message, fields)
    if not _enabled:
        return
    try:
        import sentry_sdk

        scalars = {
            key: (
                value
                if value is None or isinstance(value, (str, int, float, bool))
                else str(value)
            )
            for key, value in fields.items()
        }
        sentry_sdk.logger.info(message, attributes={"event.name": name, **scalars})
    except Exception:  # pragma: no cover
        logger.debug("Sentry log emission failed for %s", name, exc_info=True)
