import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_experiments,
    routes_graph,
    routes_history,
    routes_schema,
    routes_telemetry,
    ws,
)
from app.config import get_settings
from app.db import check_postgres_reachable, create_pool
from app.gateway.factory import build_http_client
from app.persistence.migrate import run_migrations
from app.persistence.registry import writer_registry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # One shared httpx.AsyncClient for the process lifetime, mirroring
    # app.state.pg_pool -- VLLMProvider instances (one per real-agent
    # experiment) all share this single connection pool while each
    # experiment's ModelGateway keeps its own semaphore/budget state
    # (docs/PHASE_2_PLAN.md §3). Construction can't fail (no eager
    # connection), unlike the Postgres pool.
    app.state.http_client = build_http_client()
    # Persistence is additive and must never block the app from serving live
    # (in-memory) experiments: a Postgres outage at startup degrades to
    # app.state.pg_pool = None rather than failing app startup (see
    # docs/PHASE_1_5_PLAN.md §11 "DB down at creation"). Routes that need the
    # pool check for None and skip persistence, not crash.
    pool = None
    try:
        pool = await create_pool(get_settings())
        await run_migrations(pool)
    except Exception:
        logger.exception("Postgres unavailable at startup; persistence disabled for this run")
        if pool is not None:
            await pool.close()
            pool = None
    app.state.pg_pool = pool

    yield

    # Cancel any outstanding writer drain-loop tasks before closing the pool
    # they depend on -- otherwise a still-running experiment at shutdown
    # leaks a task holding a reference to a now-closed pool.
    await writer_registry.shutdown_all()
    if app.state.pg_pool is not None:
        await app.state.pg_pool.close()
    await app.state.http_client.aclose()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_experiments.router)
app.include_router(routes_graph.router)
app.include_router(routes_history.router)
app.include_router(routes_schema.router)
app.include_router(routes_telemetry.router)
app.include_router(ws.router)


@app.get("/health")
async def health(reachable: bool = Depends(check_postgres_reachable)) -> dict[str, str]:
    return {"status": "ok", "postgres": "reachable" if reachable else "unreachable"}
