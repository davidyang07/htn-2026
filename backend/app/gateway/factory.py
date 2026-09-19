"""Selects and constructs the ModelGateway for one experiment
(docs/PHASE_2_PLAN.md §3, §8). Centralized here so routes_experiments.py
stays a thin wiring point and this selection logic is independently
testable.
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.gateway.gateway import ModelGateway
from app.gateway.mock_provider import MockProvider
from app.gateway.vllm_provider import VLLMProvider
from app.schemas.experiment import ExperimentConfig

# httpx defaults to a 5s timeout on every operation, which silently preempts
# the ModelGateway asyncio.wait_for(timeout=model_timeout_s) bound:
# model_timeout_s is configurable up to 120s, so every value above 5 was dead
# config and a slow-but-healthy vLLM call surfaced as a ModelProviderError
# instead of being allowed its configured budget. Bounding read/write/pool
# above that ceiling keeps ModelGateway the single authority on per-call
# timeout; connect keeps a short bound of its own so an unreachable host still
# fails fast.
_HTTP_TIMEOUT_S = 125.0
_HTTP_CONNECT_TIMEOUT_S = 10.0


def build_http_client() -> httpx.AsyncClient:
    """The client every ModelGateway call goes through. Built here, not at each
    call site, so the live app (app/main.py) and the benchmark runner
    (app/benchmark/runner.py) cannot drift apart on timeout policy -- they did,
    and the runner silently kept the 5s default."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(_HTTP_TIMEOUT_S, connect=_HTTP_CONNECT_TIMEOUT_S)
    )


def build_gateway(
    config: ExperimentConfig, settings: Settings, http_client: httpx.AsyncClient
) -> ModelGateway | None:
    """None whenever real_agent_count == 0 -- no gateway is constructed at
    all, so an experiment that never uses one never pays for one (no
    semaphore, no budget counter, nothing for ExperimentRunner to call)."""
    if config.real_agent_count <= 0:
        return None

    if config.model_provider == "vllm":
        # POST /api/experiments already rejected this combination with a 400
        # if vllm_base_url were unset (docs/PHASE_2_PLAN.md §8) -- this
        # assertion documents that invariant rather than re-checking it.
        assert settings.vllm_base_url is not None
        provider = VLLMProvider(
            http_client,
            base_url=settings.vllm_base_url,
            api_key=settings.vllm_api_key,
            model_name=config.model_name,
        )
    else:
        provider = MockProvider()

    return ModelGateway(
        provider,
        timeout_s=config.model_timeout_s,
        max_retries=config.model_max_retries,
        max_concurrency=config.model_max_concurrency,
        max_requests_per_experiment=config.model_max_requests_per_experiment,
    )
