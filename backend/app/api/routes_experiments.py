import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.gateway.factory import build_gateway
from app.orchestrator.registry import registry
from app.orchestrator.runner import ExperimentRunner, InvalidTransitionError
from app.persistence.registry import writer_registry
from app.persistence.writer import PostgresWriter
from app.schemas.experiment import ExperimentConfig, ExperimentSummary, SpeedRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


@router.post("", response_model=ExperimentSummary, status_code=201)
async def create_experiment(config: ExperimentConfig, request: Request) -> ExperimentSummary:
    # Fail fast (docs/PHASE_2_PLAN.md §8): never construct a runner that can
    # never make a real model call. model_provider="mock" always succeeds --
    # it needs no external service.
    if config.real_agent_count > 0 and config.model_provider == "vllm":
        if not get_settings().vllm_base_url:
            raise HTTPException(
                status_code=400,
                detail="vLLM base_url not configured; set VLLM_BASE_URL or use model_provider=mock",
            )

    gateway = build_gateway(config, get_settings(), request.app.state.http_client)
    runner = ExperimentRunner(config, gateway=gateway)

    # Persistence is additive and best-effort: a Postgres outage (no pool, or
    # a failed writer start) must never block or fail experiment creation --
    # the live run simply proceeds without a durable record for this
    # experiment (docs/PHASE_1_5_PLAN.md §11 "DB down at creation").
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is not None:
        writer = PostgresWriter(pool, runner.experiment_id, runner.bus, runner)
        try:
            await writer.start()
        except Exception:
            logger.exception(
                "PostgresWriter failed to start for experiment %s; "
                "continuing without persistence for this run",
                runner.experiment_id,
            )
        else:
            writer_registry.add(runner.experiment_id, writer)

    await runner.publish_initial()
    registry.add(runner)
    runner.start()
    return runner.summary()


@router.get("/{experiment_id}", response_model=ExperimentSummary)
async def get_experiment(experiment_id: UUID) -> ExperimentSummary:
    runner = registry.get(experiment_id)
    if runner is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return runner.summary()


@router.post("/{experiment_id}/stop", response_model=ExperimentSummary)
async def stop_experiment(experiment_id: UUID) -> ExperimentSummary:
    runner = registry.get(experiment_id)
    if runner is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    await runner.stop()
    registry.remove(experiment_id)
    return runner.summary()


@router.post("/{experiment_id}/pause", response_model=ExperimentSummary)
async def pause_experiment(experiment_id: UUID) -> ExperimentSummary:
    runner = registry.get(experiment_id)
    if runner is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    try:
        runner.pause()
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return runner.summary()


@router.post("/{experiment_id}/resume", response_model=ExperimentSummary)
async def resume_experiment(experiment_id: UUID) -> ExperimentSummary:
    runner = registry.get(experiment_id)
    if runner is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    try:
        runner.resume()
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return runner.summary()


@router.post("/{experiment_id}/speed", response_model=ExperimentSummary)
async def set_experiment_speed(experiment_id: UUID, body: SpeedRequest) -> ExperimentSummary:
    runner = registry.get(experiment_id)
    if runner is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    try:
        runner.set_speed(body.multiplier)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return runner.summary()
