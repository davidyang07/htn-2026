"""Proves persistence introduces no reordering, drops, or field corruption:
the persisted experiment_events for a real ExperimentRunner + PostgresWriter
run of the canonical seed=42 config, projected onto the same
DETERMINISM_FIELDS tuple scripts/verify_determinism.py already trusts,
exactly match a fresh in-process run_full() + EventEmitter run of the same
config. Also asserts experiments.final_* matches runner.summary() exactly.
"""

import asyncio
import json
import uuid

from app.db import create_pool
from app.engine.simulate import run_full
from app.events.emitter import EventEmitter
from app.orchestrator.runner import ExperimentRunner
from app.persistence.registry import writer_registry
from app.persistence.writer import PostgresWriter
from app.schemas.experiment import ExperimentConfig

from .conftest import TEST_SETTINGS, requires_postgres

pytestmark = requires_postgres

# Matches SPEC §6.2's canonical demo config and scripts/verify_determinism.py.
CANONICAL_CONFIG = ExperimentConfig(seed=42, node_count=60)

DETERMINISM_FIELDS = (
    "seq",
    "sim_tick",
    "event_type",
    "agent_id",
    "source_agent_id",
    "target_agent_id",
    "metadata",
)


def _ground_truth_projection() -> list[tuple]:
    drafts = run_full(CANONICAL_CONFIG)
    events = EventEmitter(experiment_id=uuid.uuid4()).emit(drafts)
    return [tuple(getattr(e, f) for f in DETERMINISM_FIELDS) for e in events]


def test_persisted_events_match_fresh_run_projected_onto_determinism_fields():
    async def run() -> None:
        pool = await create_pool(TEST_SETTINGS)
        runner = ExperimentRunner(CANONICAL_CONFIG)
        runner.tick_interval = 0
        try:
            writer = PostgresWriter(pool, runner.experiment_id, runner.bus, runner)
            await writer.start()
            writer_registry.add(runner.experiment_id, writer)
            await runner.publish_initial()
            await runner._run_loop()

            deadline = asyncio.get_event_loop().time() + 10.0
            while not writer._task.done():
                if asyncio.get_event_loop().time() > deadline:
                    raise AssertionError("writer did not finalize within the timeout")
                await asyncio.sleep(0.01)

            rows = await pool.fetch(
                "SELECT seq, sim_tick, event_type, agent_id, source_agent_id, "
                "target_agent_id, metadata "
                "FROM experiment_events WHERE experiment_id = $1 ORDER BY seq",
                runner.experiment_id,
            )
            persisted_projection = [
                (
                    r["seq"],
                    r["sim_tick"],
                    r["event_type"],
                    r["agent_id"],
                    r["source_agent_id"],
                    r["target_agent_id"],
                    json.loads(r["metadata"]),
                )
                for r in rows
            ]

            assert persisted_projection == _ground_truth_projection()

            exp_row = await pool.fetchrow(
                "SELECT final_status, final_sim_tick, final_last_seq, is_complete "
                "FROM experiments WHERE experiment_id = $1",
                runner.experiment_id,
            )
            summary = runner.summary()
            assert exp_row["final_status"] == summary.status
            assert exp_row["final_sim_tick"] == summary.sim_tick
            assert exp_row["final_last_seq"] == summary.last_seq
            assert exp_row["is_complete"] is True
        finally:
            await pool.execute(
                "DELETE FROM experiments WHERE experiment_id = $1", runner.experiment_id
            )
            await pool.close()

    asyncio.run(run())
