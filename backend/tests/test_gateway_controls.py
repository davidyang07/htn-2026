import asyncio

import pytest

from app.gateway.gateway import ModelGateway
from app.gateway.schemas import ModelProviderError, ModelRequest, ModelResponse


def _request(agent_id: str = "agent-000") -> ModelRequest:
    return ModelRequest(
        agent_id=agent_id,
        seed=1,
        tick=0,
        system_prompt="sp",
        user_message="um",
        max_tokens=16,
        mock_leak_probability=0.5,
    )


class _CountingProvider:
    """Records how many times complete() was actually called."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        return ModelResponse(text="ok", latency_ms=1.0, tokens_used=1, provider="mock")


class _AlwaysFailsProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        raise ModelProviderError("simulated failure")


class _AlwaysTimesOutProvider:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.calls = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        await asyncio.sleep(self.delay)
        return ModelResponse(
            text="too slow", latency_ms=self.delay * 1000, tokens_used=1, provider="mock"
        )


class _ConcurrencyTrackingProvider:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.current = 0
        self.max_observed = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.current += 1
        self.max_observed = max(self.max_observed, self.current)
        await asyncio.sleep(self.delay)
        self.current -= 1
        return ModelResponse(
            text="ok", latency_ms=self.delay * 1000, tokens_used=1, provider="mock"
        )


def _gateway(provider, **overrides) -> ModelGateway:
    defaults = dict(
        timeout_s=1.0, max_retries=1, max_concurrency=4, max_requests_per_experiment=1000
    )
    defaults.update(overrides)
    return ModelGateway(provider, **defaults)


def test_budget_exhaustion_stops_provider_calls():
    provider = _CountingProvider()
    gateway = _gateway(provider, max_requests_per_experiment=3)

    async def run():
        return [await gateway.complete(_request()) for _ in range(5)]

    results = asyncio.run(run())
    assert provider.calls == 3
    assert results[:3] == [r for r in results[:3] if r is not None]
    assert results[3:] == [None, None]
    assert gateway.requests_used == 3


def test_budget_exhaustion_holds_under_concurrent_load():
    """Regression for a real race: checking self._used before queuing on
    the semaphore let every caller queued past max_concurrency observe the
    same stale count and all pass the check once admitted, overrunning the
    budget -- exactly real_agent_step's asyncio.gather calling shape
    whenever a tick has more real-real attempts than max_concurrency
    (docs/PHASE_2_PLAN.md §3's "hard backstop... regardless of node_count x
    max_ticks x real-real edge count" claim)."""
    provider = _CountingProvider()
    gateway = _gateway(provider, max_concurrency=2, max_requests_per_experiment=3)

    async def run():
        return await asyncio.gather(*(gateway.complete(_request(f"a-{i}")) for i in range(10)))

    results = asyncio.run(run())
    assert provider.calls == 3
    assert gateway.requests_used == 3
    assert sum(1 for r in results if r is not None) == 3
    assert sum(1 for r in results if r is None) == 7


def test_retry_then_give_up_returns_none():
    provider = _AlwaysFailsProvider()
    gateway = _gateway(provider, max_retries=2)

    async def run():
        return await gateway.complete(_request())

    result = asyncio.run(run())
    assert result is None
    assert provider.calls == 3  # initial attempt + 2 retries


def test_timeout_triggers_retry_then_gives_up():
    provider = _AlwaysTimesOutProvider(delay=0.2)
    gateway = _gateway(provider, timeout_s=0.05, max_retries=1)

    async def run():
        return await gateway.complete(_request())

    result = asyncio.run(run())
    assert result is None
    assert provider.calls == 2  # initial attempt + 1 retry


def test_success_does_not_retry():
    provider = _CountingProvider()
    gateway = _gateway(provider, max_retries=3)

    async def run():
        return await gateway.complete(_request())

    result = asyncio.run(run())
    assert result is not None
    assert provider.calls == 1


def test_concurrency_never_exceeds_configured_max():
    provider = _ConcurrencyTrackingProvider(delay=0.05)
    gateway = _gateway(provider, max_concurrency=2, max_requests_per_experiment=100)

    async def run():
        await asyncio.gather(*(gateway.complete(_request(f"a-{i}")) for i in range(8)))

    asyncio.run(run())
    assert provider.max_observed <= 2


def test_cancellation_is_never_swallowed():
    """asyncio.CancelledError must propagate through complete() -- a gateway
    that ate it would let ExperimentRunner.stop()'s task cancellation vanish
    silently (docs/PHASE_2_PLAN.md §3, §12)."""
    provider = _AlwaysTimesOutProvider(delay=5.0)
    gateway = _gateway(provider, timeout_s=10.0, max_retries=0)

    async def run():
        task = asyncio.ensure_future(gateway.complete(_request()))
        await asyncio.sleep(0.05)
        task.cancel()
        await task

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
