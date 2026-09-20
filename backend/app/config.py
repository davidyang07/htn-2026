from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

#: backend/app/config.py -> backend/app -> backend -> the repository root,
#: where the (git-ignored) .env the operator actually edits lives. Resolved
#: from __file__ rather than the process working directory so `uvicorn` run
#: from backend/ and `pytest` run from anywhere both find the same file.
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "agentnet"
    postgres_password: str = "agentnet_dev"
    postgres_db: str = "agentnet"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Phase 2 (docs/PHASE_2_PLAN.md §8): the vLLM server endpoint/credential
    # live here, env-var-driven like postgres_*, deliberately NOT in
    # ExperimentConfig -- ExperimentConfig is persisted verbatim into
    # Postgres and returned by multiple existing read endpoints, so putting
    # infra credentials there would leak them through code that already
    # exists. Deploying a RunPod GPU pod running vLLM and setting these is a
    # manual, owner-performed step (docs/BRIEF.md §12) -- both default to
    # None, which is exactly the "vLLM isn't configured" signal
    # POST /api/experiments checks for.
    vllm_base_url: str | None = None
    vllm_api_key: str | None = None

    # Observability (docs/PROJECT.md §9). Every one of these is optional and
    # none may sit on the demo's critical path: with no DSN the SDK is never
    # initialized and the application behaves identically.
    sentry_dsn: str | None = None
    sentry_environment: str = "local"
    # Full sampling is fine for a hackathon demo: one trace per run, a handful
    # of spans each.
    sentry_traces_sample_rate: float = 1.0

    # Optional post-hoc incident explanation (docs/MVP_PLAN.md P0.14). An LLM
    # may *explain* an incident only after the deterministic decision has been
    # made and recorded; it is never an input to a policy outcome.
    # These AGENTSHIELD_MODEL_* names are shared with WorkSwarm, so its
    # sponsor/OpenRouter credential is reused rather than copied or replaced.
    agentshield_model_base_url: str | None = None
    agentshield_model_api_key: str | None = None
    agentshield_model_name: str | None = None
    agentshield_model_provider: str | None = None

    # Legacy direct-OpenAI settings remain a last-priority compatibility path.
    # They are not required for incident explanation.
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # P1 (docs/PROJECT.md §11): a self-hosted Qwen behind vLLM on RunPod, used
    # as the Replacement Researcher's model to show the immune response is
    # model-provider-independent. Absent, unreachable or unconfigured must all
    # leave the demo working.
    runpod_model_base_url: str | None = None
    runpod_model_api_key: str | None = None
    runpod_model_name: str | None = None

    def optional(self, name: str) -> str | None:
        """A configured value, or None when it is unset *or* set to the empty
        string. `.env` files are written with bare `KEY=` placeholders far more
        often than the key is deleted, and an empty string is not a credential.
        """
        value = getattr(self, name, None)
        if value is None:
            return None
        text = str(value).strip()
        return text or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
