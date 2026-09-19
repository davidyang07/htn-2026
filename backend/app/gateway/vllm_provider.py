"""Thin async client against vLLM's own OpenAI-compatible
`POST /v1/chat/completions` contract (docs/PHASE_2_PLAN.md §3). No vLLM SDK,
no RunPod SDK -- a RunPod GPU pod running `vllm serve ...` is, from this
codebase's point of view, just an HTTP endpoint behind `settings.vllm_base_url`.
"""

from __future__ import annotations

import time

import httpx

from app.gateway.schemas import ModelProviderError, ModelRequest, ModelResponse


class VLLMProvider:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str,
        api_key: str | None,
        model_name: str,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name

    async def complete(self, request: ModelRequest) -> ModelResponse:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        payload = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_message},
            ],
            "max_tokens": request.max_tokens,
        }
        start = time.monotonic()
        try:
            resp = await self._client.post(
                f"{self._base_url}/v1/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Never log `payload`/`data` wholesale here -- system_prompt
            # embeds the target's confidential_token in plaintext
            # (docs/PHASE_2_PLAN.md §10's logging discipline).
            raise ModelProviderError(f"vLLM request failed for agent_id={request.agent_id}: "
                                      f"{type(exc).__name__}") from exc
        latency_ms = (time.monotonic() - start) * 1000

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelProviderError(
                f"unexpected vLLM response shape for agent_id={request.agent_id}"
            ) from exc

        tokens_used = data.get("usage", {}).get("total_tokens") or max(1, len(text) // 4)

        return ModelResponse(
            text=text,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            provider="vllm",
        )
