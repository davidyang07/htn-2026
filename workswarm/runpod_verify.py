"""Credential-safe verification helpers for an OpenAI-compatible RunPod pod."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class EndpointUrls:
    """Canonical vLLM endpoints derived from one configured base URL."""

    service_root: str
    openai_base: str
    health: str
    models: str
    chat_completions: str


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
