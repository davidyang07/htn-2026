"""Resolve the optional explanation model without owning any credentials."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Protocol
from urllib.parse import urlparse

from app.config import REPO_ROOT, Settings


class CompatibleModelConfig(Protocol):
    provider: str
    model_name: str
    api_key: str
    api_base: str
    source: str

    @property
    def configured(self) -> bool: ...


@dataclass(frozen=True, repr=False)
class ExplanationProvider:
    """Only what an OpenAI-compatible explanation call needs."""

    provider: str
    model: str
    api_base: str
    api_key: str | None
    source: str

    @property
    def chat_completions_url(self) -> str:
        base = self.api_base.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def __repr__(self) -> str:
        return (
            f"ExplanationProvider(provider={self.provider!r}, model={self.model!r}, "
            f"api_base={self.api_base!r}, source={self.source!r}, "
            f"api_key=<{'set' if self.api_key else 'unset'}>)"
        )


def _load_workswarm_module(path: Path) -> ModuleType | None:
    """Load the repository's resolver even when uvicorn starts in backend/."""
    if not path.is_file():
        return None
    module_name = "_agentshield_workswarm_config"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None
    finally:
        sys.modules.pop(module_name, None)


def _workswarm_resolver() -> CompatibleModelConfig | None:
    """Reuse WorkSwarm's established precedence and config.yaml support."""
    module = _load_workswarm_module(REPO_ROOT / "workswarm" / "config.py")
    resolver = getattr(module, "resolve_model", None) if module is not None else None
    if not callable(resolver):
        return None
    try:
        return resolver()
    except Exception:
        return None


def _from_settings(settings: Settings) -> ExplanationProvider | None:
    """Container-safe fallback for the same shared AGENTSHIELD_MODEL_* env."""
    base = settings.optional("agentshield_model_base_url")
    model = settings.optional("agentshield_model_name")
    if base and model:
        return ExplanationProvider(
            provider=_provider_name(
                settings.optional("agentshield_model_provider"), base
            ),
            model=model,
            api_base=base,
            api_key=settings.optional("agentshield_model_api_key"),
            source="AGENTSHIELD_MODEL_*",
        )

    # Backward-compatible only: a direct OpenAI key is supported but is not
    # required and is lower priority than the WorkSwarm/sponsor model.
    openai_key = settings.optional("openai_api_key")
    if openai_key:
        return ExplanationProvider(
            provider="OpenAI",
            model=settings.openai_model,
            api_base=settings.openai_base_url,
            api_key=openai_key,
            source="legacy OPENAI_*",
        )
    return None


def _provider_name(configured_name: str | None, api_base: str) -> str:
    """Name the service, not merely its OpenAI-compatible client adapter."""
    hostname = (urlparse(api_base).hostname or "").lower()
    if hostname == "openrouter.ai" or hostname.endswith(".openrouter.ai"):
        return "OpenRouter"
    return (configured_name or "OpenAI-compatible").strip() or "OpenAI-compatible"


def resolve_explanation_provider(
    settings: Settings,
    workswarm_resolver: Callable[[], CompatibleModelConfig | None] = _workswarm_resolver,
) -> ExplanationProvider | None:
    """Resolve safely; absence or malformed configuration means no provider."""
    try:
        model = workswarm_resolver()
    except Exception:
        model = None
    if model is not None and model.configured:
        base = str(model.api_base).strip()
        name = str(model.model_name).strip()
        if base and name:
            key = str(model.api_key).strip() or None
            return ExplanationProvider(
                provider=_provider_name(str(model.provider), base),
                model=name,
                api_base=base,
                api_key=key if key != "not-required" else None,
                source=str(model.source),
            )
    return _from_settings(settings)
