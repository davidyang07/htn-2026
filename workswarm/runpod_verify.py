"""Credential-safe verification helpers for an OpenAI-compatible RunPod pod."""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from workswarm.config import ModelConfig


@dataclass(frozen=True)
class EndpointUrls:
    """Canonical vLLM endpoints derived from one configured base URL."""

    service_root: str
    openai_base: str
    health: str
    models: str
    chat_completions: str


@dataclass(frozen=True)
class ProbeResult:
    """One credential-free endpoint observation."""

    name: str
    ok: bool
    status_code: int | None
    latency_ms: int
    detail: str


@dataclass(frozen=True)
class ModelsResult:
    """Result of verifying that vLLM advertises the configured model."""

    probe: ProbeResult
    model_ids: tuple[str, ...]
    expected_model_found: bool


@dataclass(frozen=True)
class ChatResult:
    """Result of one minimal OpenAI-compatible completion."""

    probe: ProbeResult
    response_chars: int


def endpoint_urls(base_url: str) -> EndpointUrls:
    """Normalize either a vLLM service root or its ``/v1`` API base.

    Userinfo, query strings, and fragments are refused so a credential cannot
    accidentally be copied into output from the verifier.
    """
    raw = (base_url or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("RunPod base URL must be an absolute http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("RunPod base URL must not contain credentials, query, or fragment")

    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        root_path = path[:-3].rstrip("/")
    else:
        root_path = path

    service_root = urlunsplit((parsed.scheme, parsed.netloc, root_path, "", "")).rstrip("/")
    openai_base = f"{service_root}/v1"
    return EndpointUrls(
        service_root=service_root,
        openai_base=openai_base,
        health=f"{service_root}/health",
        models=f"{openai_base}/models",
        chat_completions=f"{openai_base}/chat/completions",
    )


class RunPodVerifier:
    """Small synchronous verifier used before the WorkSwarm run starts."""

    def __init__(
        self,
        model: ModelConfig,
        *,
        client: httpx.Client | None = None,
        timeout_s: float = 5.0,
    ) -> None:
        self.model = model
        self.urls = endpoint_urls(model.api_base)
        headers = (
            {"Authorization": f"Bearer {model.api_key}"}
            if model.api_key and model.api_key != "not-required"
            else {}
        )
        self._client = client or httpx.Client(headers=headers, timeout=timeout_s)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def probe_health(self) -> ProbeResult:
        """GET ``/health`` without ever returning response content."""
        started = time.perf_counter()
        try:
            response = self._client.get(self.urls.health)
        except httpx.RequestError as exc:
            return ProbeResult(
                name="health",
                ok=False,
                status_code=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
                detail=f"request failed ({type(exc).__name__})",
            )

        return ProbeResult(
            name="health",
            ok=response.status_code == 200,
            status_code=response.status_code,
            latency_ms=int((time.perf_counter() - started) * 1000),
            detail="healthy" if response.status_code == 200 else "unexpected HTTP status",
        )

    def probe_models(self) -> ModelsResult:
        """GET ``/v1/models`` and require the configured model id."""
        started = time.perf_counter()
        try:
            response = self._client.get(self.urls.models)
        except httpx.RequestError as exc:
            return ModelsResult(
                probe=ProbeResult(
                    name="models",
                    ok=False,
                    status_code=None,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    detail=f"request failed ({type(exc).__name__})",
                ),
                model_ids=(),
                expected_model_found=False,
            )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code != 200:
            return ModelsResult(
                probe=ProbeResult(
                    name="models",
                    ok=False,
                    status_code=response.status_code,
                    latency_ms=elapsed_ms,
                    detail="unexpected HTTP status",
                ),
                model_ids=(),
                expected_model_found=False,
            )

        try:
            payload = response.json()
            rows = payload["data"]
            model_ids = tuple(
                str(row["id"]) for row in rows if isinstance(row, dict) and row.get("id")
            )
        except (KeyError, TypeError, ValueError):
            model_ids = ()

        expected = self.model.model_name in model_ids
        detail = "configured model advertised" if expected else "configured model not advertised"
        return ModelsResult(
            probe=ProbeResult(
                name="models",
                ok=expected,
                status_code=response.status_code,
                latency_ms=elapsed_ms,
                detail=detail,
            ),
            model_ids=model_ids,
            expected_model_found=expected,
        )

    def probe_chat(self, *, max_tokens: int = 16) -> ChatResult:
        """POST one tiny completion and validate the OpenAI response shape."""
        started = time.perf_counter()
        try:
            response = self._client.post(
                self.urls.chat_completions,
                json={
                    "model": self.model.model_name,
                    "messages": [{"role": "user", "content": "Reply with exactly: ready"}],
                    "temperature": 0,
                    "max_tokens": max_tokens,
                },
            )
        except httpx.RequestError as exc:
            return ChatResult(
                probe=ProbeResult(
                    name="chat",
                    ok=False,
                    status_code=None,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    detail=f"request failed ({type(exc).__name__})",
                ),
                response_chars=0,
            )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code != 200:
            return ChatResult(
                probe=ProbeResult(
                    name="chat",
                    ok=False,
                    status_code=response.status_code,
                    latency_ms=elapsed_ms,
                    detail="unexpected HTTP status",
                ),
                response_chars=0,
            )

        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            valid = isinstance(content, str) and bool(content.strip())
        except (IndexError, KeyError, TypeError, ValueError):
            content = ""
            valid = False

        return ChatResult(
            probe=ProbeResult(
                name="chat",
                ok=valid,
                status_code=response.status_code,
                latency_ms=elapsed_ms,
                detail="completion returned" if valid else "malformed completion response",
            ),
            response_chars=len(content) if isinstance(content, str) else 0,
        )
