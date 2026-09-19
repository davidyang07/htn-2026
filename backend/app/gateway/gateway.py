"""ModelGateway: the single object real-agent code calls into (never a bare
provider) so every cost/safety control lives in exactly one place
(docs/PHASE_2_PLAN.md §3). One instance per experiment -- constructed by
ExperimentRunner -- so its request budget is genuinely per-experiment, not
global or per-tick.
"""

from __future__ import annotations

import asyncio
import logging

from app.gateway.schemas import ModelProvider, ModelProviderError, ModelRequest, ModelResponse

logger = logging.getLogger(__name__)

_RETRY_BACKOFF_S = 0.1


class ModelGateway:
    def __init__(
        self,
        provider: ModelProvider,
        *,
        timeout_s: float,
        max_retries: int,
        max_concurrency: int,
        max_requests_per_experiment: int,
    ) -> None:
        self._provider = provider
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._budget = max_requests_per_experiment
        self._used = 0

    @property
    def requests_used(self) -> int:
        return self._used

    async def complete(self, request: ModelRequest) -> ModelResponse | None:
        """None means: budget exhausted, or every retry failed/timed out.
        Never raises for a provider/timeout failure -- a model outage
        degrades this attempt to a controlled failure, never the live run.
        `asyncio.CancelledError` (a BaseException) is never caught here and
        always propagates, so ExperimentRunner.stop()'s task cancellation is
        never silently swallowed mid-call.

        The budget check-and-increment happens *after* acquiring the
        semaphore, not before: checking `self._used` before queuing on the
        semaphore lets multiple callers queued past `max_concurrency` each
        observe the same stale count and all pass the check once the
        semaphore admits them, overrunning the budget under concurrent load
        (real_agent_step's asyncio.gather is exactly this shape whenever a
        tick has more real-real attempts than max_concurrency). Checking and
        incrementing back-to-back with no `await` between them, once inside
        the semaphore, is atomic under asyncio's cooperative scheduling."""
        async with self._semaphore:
            if self._used >= self._budget:
                return None
            self._used += 1
            for attempt in range(self._max_retries + 1):
                try:
                    return await asyncio.wait_for(
                        self._provider.complete(request), timeout=self._timeout_s
                    )
                except (ModelProviderError, TimeoutError) as exc:
                    if attempt == self._max_retries:
                        logger.warning(
                            "model gateway giving up for agent_id=%s after %d attempt(s): %s",
                            request.agent_id,
                            attempt + 1,
                            type(exc).__name__,
                        )
                        return None
                    await asyncio.sleep(_RETRY_BACKOFF_S)
        return None
