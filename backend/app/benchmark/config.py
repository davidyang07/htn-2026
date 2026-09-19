"""BenchmarkConfig: an ExperimentConfig subclass used ONLY by the offline
app/benchmark/ package to run large-scale (2,500+ agent) simulations.

Flagged deviation from docs/SPEC.md §4's node_count in [25, 100] bound: the
live, API-facing ExperimentConfig used by routes_experiments.py, the
WebSocket transport, and NetworkGraph.tsx keeps its [25, 100] bound
completely unchanged -- this subclass is never constructed from an HTTP
request body, never returned by an API response, and never reaches the
frontend. It exists solely so app/benchmark/matrix.py's scale-run preset can
call the exact same deterministic engine.simulate()/build_world() code path
at a size the live product's browser-rendered graph was never designed for.
"""

from __future__ import annotations

from pydantic import Field

from app.schemas.experiment import ExperimentConfig


class BenchmarkConfig(ExperimentConfig):
    node_count: int = Field(60, ge=25, le=3000)
