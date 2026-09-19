from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
