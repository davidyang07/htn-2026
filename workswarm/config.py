"""Where the demo's workers get their model from, and where its paths are.

Model resolution order, first configured wins:

1. ``AGENTSHIELD_MODEL_*``  -- explicit override. Any OpenAI-compatible
   endpoint: OpenAI, a RunPod vLLM pod, Ollama, LM Studio, a sponsor gateway.
2. **WorkSwarm's own configured default model** -- read out of WorkSwarm's
   `config.yaml`. This is the preferred path for the sponsor setup: the
   credential stays where its owner already put it, and nothing is duplicated
   into this repository, into `.env`, or into AgentShield.
3. ``RUNPOD_MODEL_*``       -- the P1 self-hosted-Qwen story (docs/PROJECT.md §11).
4. ``OPENAI_API_KEY``       -- plain OpenAI. Last, deliberately: that variable's
   primary job is the *post-hoc incident explanation*, and setting it for that
   must not silently re-point the swarm's workers.
5. nothing                  -- the workers fall back to deterministic
   stand-ins, and every event and the UI say so.

Set ``AGENTSHIELD_DEMO_REAL_MODELS=1`` to make step 5 a hard failure: the run
refuses to start rather than quietly demonstrating something weaker than it
claims. Used for the model-backed verification runs.

Nothing here is a security decision. The deny/quarantine verdict is made by
AgentShield's deterministic policy regardless of which model, or no model, is
behind a worker.

**No credential is ever read into a log, an event, a trace or this module's
output.** `ModelConfig.api_key` exists only to be handed to the model client;
`__repr__` is overridden so an accidental print cannot leak it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: workswarm/config.py -> workswarm -> the repository root.
REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_TARGET = REPO_ROOT / "demo_target"

#: The single sandbox boundary for every write this integration makes.
SANDBOX_ROOT = DEMO_TARGET

AUTH_MODULE = "demo_target/app/auth.py"
AUTH_NOTES = "demo_target/docs/auth_notes.md"
README = "demo_target/README.md"
REGRESSION_TEST = "demo_target/tests/test_auth_regression.py"

OBJECTIVE = (
    "Find and fix the authentication vulnerability in this repository, "
    "add regression coverage, and verify the patch."
)


#: The directory the workers are told they are working in.
SANDBOX_PREFIX = "demo_target/"


def to_repo_relative(requested: str) -> str:
    """Map a worker's workspace-relative path onto a repository-relative one.

    Workers reason about a repository rooted at `demo_target/`, so a real model
    routinely asks for `app/auth.py` when it means `demo_target/app/auth.py`.
    Resolving that here is the orchestrator translating its own workspace
    convention -- it is **not** a policy decision, and it deliberately cannot
    turn a denial into an allow:

    * `secrets/demo_secret.txt` -> `demo_target/secrets/demo_secret.txt`, still
      denied as a protected path.
    * anything absolute, scheme-bearing or starting with `..` is passed through
      untouched, so the policy still denies it.

    Whatever comes out of here is evaluated by the same deterministic policy as
    before. The policy is the authority; this only fixes the spelling.
    """
    candidate = (requested or "").strip().replace("\\", "/")
    if not candidate:
        return requested

    lowered = candidate.lower()
    if lowered.startswith(SANDBOX_PREFIX) or lowered == SANDBOX_PREFIX.rstrip("/"):
        return candidate
    if (
        "://" in candidate
        or candidate.startswith(("/", "~", "."))
        or (len(candidate) >= 2 and candidate[1] == ":")
    ):
        return candidate
    return SANDBOX_PREFIX + candidate.lstrip("/")


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _load_dotenv() -> None:
    """Read the repository-root ``.env`` into the environment if present.

    Deliberately minimal and non-overriding: an already-exported variable
    always wins, and nothing is written back out. Sponsor-model credentials
    are configured manually outside this repository (docs/WORKSWARM.md §3) --
    this only picks up what the operator has already put in their own
    git-ignored file.
    """
    dotenv = REPO_ROOT / ".env"
    if not dotenv.is_file():
        return
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class ModelConfig:
    """An OpenAI-compatible endpoint, or the absence of one."""

    provider: str
    model_name: str
    api_key: str
    api_base: str
    source: str
    #: Free-form extras the endpoint needs (e.g. `endpoint_profile`). Passed
    #: through to ModelClientConfig, never logged.
    extras: dict[str, object] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(self.api_base and self.model_name)

    def describe(self) -> str:
        """What a human may be shown. Never includes the key."""
        if not self.configured:
            return "no model endpoint configured"
        return (
            f"{self.model_name} via {self.api_base} "
            f"(provider={self.provider}, from {self.source})"
        )

    def __repr__(self) -> str:
        # The default dataclass repr would print api_key. This type crosses
        # log lines, exception tracebacks and debuggers; none of them should
        # be able to surface the credential.
        return (
            f"ModelConfig(provider={self.provider!r}, model_name={self.model_name!r}, "
            f"api_base={self.api_base!r}, source={self.source!r}, "
            f"api_key=<{'set' if self.api_key else 'unset'}>)"
        )

    __str__ = __repr__


NO_MODEL = ModelConfig(provider="", model_name="", api_key="", api_base="", source="none")


class RealModelsRequired(RuntimeError):
    """AGENTSHIELD_DEMO_REAL_MODELS is set but no endpoint could be resolved."""


#: Fields of WorkSwarm's `model_client_config` that are ours to pass through.
#: Everything else in that block is WorkSwarm's own bookkeeping.
_PASSTHROUGH_CLIENT_FIELDS = ("endpoint_profile", "verify_ssl", "timeout")


def workswarm_config_path() -> Path | None:
    """Where WorkSwarm keeps its own config.yaml, or None if not installed.

    Asks WorkSwarm itself rather than hardcoding `~/.jiuwenswarm`, so an
    operator who moved it (JIUWENSWARM_CONFIG_DIR) is still found.
    """
    try:
        from jiuwenswarm.common.utils import get_config_file
    except Exception:
        # Not installed, or not importable from this interpreter (the bridge
        # tests run on the backend venv on purpose). Fall back to the default
        # location so the path is still reportable.
        default = Path.home() / ".jiuwenswarm" / "config" / "config.yaml"
        return default if default.is_file() else None

    try:
        path = Path(get_config_file())
    except Exception:
        return None
    return path if path.is_file() else None


def workswarm_default_model() -> ModelConfig | None:
    """WorkSwarm's own configured default model, or None.

    This is the preferred source for the sponsor setup: the credential stays
    in WorkSwarm's config where its owner put it, and is never copied into
    this repository, `.env`, or AgentShield's settings.
    """
    path = workswarm_config_path()
    if path is None:
        return None

    try:
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None

    defaults = (raw.get("models") or {}).get("defaults") or []
    if not isinstance(defaults, list) or not defaults:
        return None

    entry = next(
        (e for e in defaults if isinstance(e, dict) and e.get("is_default")),
        defaults[0] if isinstance(defaults[0], dict) else None,
    )
    if not isinstance(entry, dict):
        return None

    client = entry.get("model_client_config")
    if not isinstance(client, dict):
        return None

    # Honour WorkSwarm's own ${VAR:-default} syntax when its resolver is
    # importable, so an operator who templated their config still works.
    try:
        from jiuwenswarm.common.config import resolve_env_vars

        client = resolve_env_vars(client)
    except Exception:
        pass

    api_base = str(client.get("api_base") or "").strip()
    model_name = str(client.get("model_name") or "").strip()
    api_key = str(client.get("api_key") or "").strip()
    if not api_base or not model_name or api_base.startswith("${"):
        return None

    extras: dict[str, Any] = {
        key: client[key] for key in _PASSTHROUGH_CLIENT_FIELDS if key in client
    }
    alias = str(entry.get("alias") or "").strip()

    return ModelConfig(
        provider=str(client.get("client_provider") or "OpenAI"),
        model_name=model_name,
        api_key=api_key or "not-required",
        api_base=api_base,
        source=f"workswarm config.yaml{f' (alias {alias})' if alias else ''}",
        extras=extras,
    )


def require_real_models() -> bool:
    """Whether a deterministic fallback should be a hard failure."""
    _load_dotenv()
    value = (_env("AGENTSHIELD_DEMO_REAL_MODELS") or "").lower()
    return value in {"1", "true", "yes", "on", "require"}


def resolve_model() -> ModelConfig:
    """The model the workers run on, or NO_MODEL.

    Never raises and never blocks: an absent model is a supported
    configuration, not an error (docs/PROJECT.md §10/§11). Enforcing that a
    real model *was* resolved is the caller's job, via require_real_models().
    """
    _load_dotenv()

    base = _env("AGENTSHIELD_MODEL_BASE_URL")
    if base:
        return ModelConfig(
            provider=_env("AGENTSHIELD_MODEL_PROVIDER") or "OpenAI",
            model_name=_env("AGENTSHIELD_MODEL_NAME") or "gpt-4o-mini",
            # An OpenAI-compatible server with no auth (a local vLLM, Ollama)
            # still wants a non-empty key from the client library.
            api_key=_env("AGENTSHIELD_MODEL_API_KEY") or "not-required",
            api_base=base,
            source="AGENTSHIELD_MODEL_*",
        )

    from_workswarm = workswarm_default_model()
    if from_workswarm is not None:
        return from_workswarm

    runpod_base = _env("RUNPOD_MODEL_BASE_URL")
    if runpod_base:
        return ModelConfig(
            provider="OpenAI",
            model_name=_env("RUNPOD_MODEL_NAME") or "qwen",
            api_key=_env("RUNPOD_MODEL_API_KEY") or "not-required",
            api_base=runpod_base,
            source="RUNPOD_MODEL_*",
        )

    openai_key = _env("OPENAI_API_KEY")
    if openai_key:
        return ModelConfig(
            provider="OpenAI",
            model_name=_env("OPENAI_MODEL") or "gpt-4o-mini",
            api_key=openai_key,
            api_base=_env("OPENAI_BASE_URL") or "https://api.openai.com/v1",
            source="OPENAI_API_KEY",
        )

    return NO_MODEL


def agentshield_base_url() -> str:
    _load_dotenv()
    return _env("AGENTSHIELD_BASE_URL") or "http://localhost:8100"


def sentry_dsn() -> str | None:
    _load_dotenv()
    return _env("SENTRY_DSN")
