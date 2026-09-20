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
