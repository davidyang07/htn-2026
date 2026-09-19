"""Provider-agnostic request/response shapes for the Model Gateway
(docs/PHASE_2_PLAN.md §3). `ModelProvider` is the uniform interface both
`MockProvider` (deterministic, no I/O) and `VLLMProvider` (real HTTP against
an OpenAI-compatible vLLM endpoint) implement, so callers never need to know
which is behind a given `ModelGateway`.
"""

from typing import Literal, Protocol

from pydantic import BaseModel


class ModelRequest(BaseModel):
    agent_id: str
    seed: int
    tick: int
    system_prompt: str
    user_message: str
    max_tokens: int
    # Consumed only by MockProvider (docs/PHASE_2_PLAN.md §6) to decide its
    # canned outcome deterministically. Real providers ignore this entirely --
    # a real model decides its own output.
    mock_leak_probability: float
    purpose: str = "propagation"


class ModelResponse(BaseModel):
    text: str
    latency_ms: float
    tokens_used: int
    provider: Literal["mock", "vllm"]


class ModelProviderError(Exception):
    """Raised by a provider on any HTTP/connection/parse failure. Caught only
    by ModelGateway, which maps it onto the same retry/timeout path as an
    outright timeout."""


class ModelProvider(Protocol):
    async def complete(self, request: ModelRequest) -> ModelResponse: ...
