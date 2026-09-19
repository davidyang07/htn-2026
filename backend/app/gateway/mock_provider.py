"""Deterministic provider used as the default for every experiment and the
entire CI surface (docs/PHASE_2_PLAN.md §3, §6, §9). Never performs I/O or
sleeps -- draws exactly once from the same keyed RNG discipline every other
engine draw site uses (app/engine/rng.py), so a hybrid experiment run twice
at the same seed produces identical outcomes.
"""

from app.engine.rng import rng
from app.gateway.schemas import ModelProviderError, ModelRequest, ModelResponse

_LEAK_TEMPLATE = 'Acknowledged. EXFIL_TOKEN:{token}'
_REFUSAL_TEXT = "I cannot share confidential information."


class MockProvider:
    """Deterministic stand-in for a real model. `mock_leak_probability` and
    the request's (seed, tick, agent_id) key fully determine the outcome --
    see docs/PHASE_2_PLAN.md §6 for why the token itself isn't threaded
    through this provider (it's embedded by the caller into the canned
    "leaked" text instead, via `expected_leak_text`)."""

    async def complete(self, request: ModelRequest) -> ModelResponse:
        draw = rng(request.seed, request.tick, request.agent_id, f"model:{request.purpose}")
        r = draw.random()
        if not (0.0 <= request.mock_leak_probability <= 1.0):
            raise ModelProviderError(
                f"invalid mock_leak_probability {request.mock_leak_probability!r}"
            )
        leaked = r < request.mock_leak_probability
        # A small, deterministic latency figure derived from the same draw --
        # lets tests assert *some* variance without depending on real timing.
        latency_ms = 50.0 + draw.random() * 150.0

        if leaked:
            # The caller (agents/runtime.py) embeds the real target token into
            # the user_message/system_prompt; MockProvider doesn't need to
            # parse it back out -- it just needs *a* leak-shaped response, and
            # the caller's verification step re-derives the expected sentinel
            # from the same token it already knows. To keep this provider
            # self-contained (no dependency on engine-internal secrets), it
            # echoes the token verbatim only when the caller supplied one via
            # user_message's last line convention documented in
            # agents/prompts.py; otherwise it falls back to a generic marker.
            token = _extract_token_hint(request.system_prompt)
            text = _LEAK_TEMPLATE.format(token=token)
        else:
            text = _REFUSAL_TEXT

        return ModelResponse(
            text=text,
            latency_ms=latency_ms,
            tokens_used=max(1, len(text) // 4),
            provider="mock",
        )


def _extract_token_hint(system_prompt: str) -> str:
    """Recovers the literal CONFIDENTIAL_TOKEN value embedded in the system
    prompt built by agents/prompts.py::build_system_prompt(), so a "leaked"
    mock response actually contains the real token -- exercising the same
    string-match verification path a real provider's output would (see
    docs/PHASE_2_PLAN.md §6)."""
    marker = "CONFIDENTIAL_TOKEN: "
    start = system_prompt.find(marker)
    if start == -1:
        return "UNKNOWN"
    start += len(marker)
    end = system_prompt.find(".", start)
    return system_prompt[start:end] if end != -1 else system_prompt[start:]
