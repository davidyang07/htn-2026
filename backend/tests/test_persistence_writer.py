"""Postgres-backed integration coverage for PostgresWriter: seq ordering,
natural-finish vs manual-stop finalization, duplicate-write idempotency,
writer cleanup, no event loss under a burst larger than the drain batch cap,
and -- the centerpiece of docs/PHASE_1_5_PLAN.md's correction to the plan --
detecting a mid-run write failure as an incomplete/untrustworthy run even
when the run otherwise finishes and finalizes "successfully".
"""

import asyncio

from app.db import create_pool
from app.orchestrator.runner import ExperimentRunner
from app.persistence.registry import writer_registry
from app.persistence.writer import DRAIN_BATCH_CAP, PostgresWriter
from app.schemas.events import EventDraft, EventType
from app.schemas.experiment import ExperimentConfig

from .conftest import TEST_SETTINGS, requires_postgres

pytestmark = requires_postgres

FINALIZE_TIMEOUT_S = 5.0


def _make_runner(**overrides) -> ExperimentRunner:
    defaults = {"seed": 42, "node_count": 25, "max_ticks": 5}
    defaults.update(overrides)
    runner = ExperimentRunner(ExperimentConfig(**defaults))
    runner.tick_interval = 0
    return runner


async def _start_writer(pool, runner: ExperimentRunner) -> PostgresWriter:
    """Mirrors the exact production call site in routes_experiments.py --
    writer_registry.add() happens at the call site, not inside
    PostgresWriter itself, so a test driving a writer directly must
    replicate that registration to exercise the real integration."""
    writer = PostgresWriter(pool, runner.experiment_id, runner.bus, runner)
    await writer.start()
    writer_registry.add(runner.experiment_id, writer)
    return writer


async def _wait_for_finalize(writer: PostgresWriter) -> None:
    assert writer._task is not None
    deadline = asyncio.get_event_loop().time() + FINALIZE_TIMEOUT_S
    while not writer._task.done():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("writer did not finalize within the timeout")
        await asyncio.sleep(0.01)


async def _cleanup(pool, experiment_id) -> None:
    await pool.execute("DELETE FROM experiments WHERE experiment_id = $1", experiment_id)


def test_events_persist_in_seq_order_and_finalize_on_natural_completion():
    async def run() -> None:
        pool = await create_pool(TEST_SETTINGS)
        runner = _make_runner()
        try:
            writer = await _start_writer(pool, runner)
            await runner.publish_initial()
            await runner._run_loop()

            await _wait_for_finalize(writer)

            rows = await pool.fetch(
                "SELECT seq FROM experiment_events WHERE experiment_id = $1 ORDER BY seq",
                runner.experiment_id,
            )
            seqs = [r["seq"] for r in rows]
            assert seqs == list(range(runner._emitter.last_seq + 1))

            exp_row = await pool.fetchrow(
                "SELECT final_status, final_sim_tick, final_last_seq, is_complete "
                "FROM experiments WHERE experiment_id = $1",
                runner.experiment_id,
            )
            assert exp_row["final_status"] == "finished"
            assert exp_row["final_sim_tick"] == runner.state.tick
            assert exp_row["final_last_seq"] == runner._emitter.last_seq
            assert exp_row["is_complete"] is True

            # Writer cleanup: no dangling bus subscription, and the writer
            # registry no longer references this experiment.
            assert len(runner.bus._subscribers) == 0
            assert writer_registry.get(runner.experiment_id) is None
        finally:
            await _cleanup(pool, runner.experiment_id)
            await pool.close()

    asyncio.run(run())


def test_finalize_on_manual_stop_persists_the_stopped_event_and_status():
    async def run() -> None:
        pool = await create_pool(TEST_SETTINGS)
        runner = _make_runner(max_ticks=1000)
        try:
            writer = await _start_writer(pool, runner)
            await runner.publish_initial()
            runner.start()
            await asyncio.sleep(0)

            await runner.stop()
            await _wait_for_finalize(writer)

            exp_row = await pool.fetchrow(
                "SELECT final_status, final_last_seq, is_complete "
                "FROM experiments WHERE experiment_id = $1",
                runner.experiment_id,
            )
            assert exp_row["final_status"] == "stopped"
            assert exp_row["final_last_seq"] == runner._emitter.last_seq
            assert exp_row["is_complete"] is True

            stopped_count = await pool.fetchval(
                "SELECT count(*) FROM experiment_events "
                "WHERE experiment_id = $1 AND event_type = $2",
                runner.experiment_id,
                "EXPERIMENT_STOPPED",
            )
            assert stopped_count == 1
            assert writer_registry.get(runner.experiment_id) is None
        finally:
            await _cleanup(pool, runner.experiment_id)
            await pool.close()

    asyncio.run(run())


def test_duplicate_batch_write_is_idempotent():
    async def run() -> None:
        pool = await create_pool(TEST_SETTINGS)
        runner = _make_runner()
        writer = PostgresWriter(pool, runner.experiment_id, runner.bus, runner)
        try:
            await writer.start()
            events = runner._emitter.emit(
                [EventDraft(sim_tick=0, event_type=EventType.EXPERIMENT_STARTED)]
            )

            await writer._write_batch(events)
            await writer._write_batch(events)  # simulated retry of the same batch

            count = await pool.fetchval(
                "SELECT count(*) FROM experiment_events WHERE experiment_id = $1 AND seq = $2",
                runner.experiment_id,
                events[0].seq,
            )
            assert count == 1
        finally:
            await writer.cancel()
            await _cleanup(pool, runner.experiment_id)
            await pool.close()

    asyncio.run(run())


def test_no_event_loss_under_a_burst_larger_than_the_drain_batch_cap():
    async def run() -> None:
        pool = await create_pool(TEST_SETTINGS)
        # defense_enabled=False plus high propagation probabilities produces
        # well over DRAIN_BATCH_CAP (500) events for a 100-node run -- this
        # proves multi-batch draining under a fast burst (tick_interval=0,
        # no yielding between ticks beyond asyncio.sleep(0)) loses nothing,
        # exercising the EventBus's unbounded per-subscriber queue rather
        # than a bespoke buffering path.
        runner = _make_runner(
            node_count=100, max_ticks=200, defense_enabled=False, p_same=0.4, p_cross=0.1
        )
        try:
            writer = await _start_writer(pool, runner)
            await runner.publish_initial()
            await runner._run_loop()

            await _wait_for_finalize(writer)

            total = runner._emitter.last_seq + 1
            assert total > DRAIN_BATCH_CAP, "test fixture must exceed the batch cap"

            rows = await pool.fetch(
                "SELECT seq FROM experiment_events WHERE experiment_id = $1 ORDER BY seq",
                runner.experiment_id,
            )
            seqs = [r["seq"] for r in rows]
            assert seqs == list(range(total))
        finally:
            await _cleanup(pool, runner.experiment_id)
            await pool.close()

    asyncio.run(run())


def test_incomplete_run_detected_when_a_batch_fails_then_recovers():
    """The correction to docs/PHASE_1_5_PLAN.md: a run that finishes and
    finalizes "successfully" (final_status populated) but suffered a
    transient mid-run write failure must be marked is_complete=False, not
    presented as a trustworthy complete run. A naive "log the failed batch
    and move on" design with no completeness check would fail this test."""

    async def run() -> None:
        pool = await create_pool(TEST_SETTINGS)
        runner = _make_runner(max_ticks=3)
        writer = PostgresWriter(pool, runner.experiment_id, runner.bus, runner)
        try:
            await writer.start()  # inserts the experiments row for real

            batch_1 = runner._emitter.emit(
                [EventDraft(sim_tick=0, event_type=EventType.EXPERIMENT_STARTED)]
            )
            await writer._write_batch(batch_1)  # seq 0: persists successfully

            class _BrokenPool:
                def acquire(self, *args: object, **kwargs: object) -> None:
                    raise RuntimeError("simulated transient DB outage")

            real_pool = writer._pool
            writer._pool = _BrokenPool()
            batch_2 = runner._emitter.emit(
                [
                    EventDraft(
                        sim_tick=0, event_type=EventType.AGENT_CREATED, agent_id="agent-000"
                    )
                ]
            )
            await writer._write_batch(batch_2)  # seq 1: logged and skipped -> a gap

            writer._pool = real_pool  # DB "recovers"
            batch_3 = runner._emitter.emit(
                [EventDraft(sim_tick=1, event_type=EventType.EXPERIMENT_STOPPED)]
            )
            await writer._write_batch(batch_3)  # seq 2: persists successfully

            runner.status = "stopped"
            await writer._finalize()

            exp_row = await pool.fetchrow(
                "SELECT final_status, is_complete FROM experiments WHERE experiment_id = $1",
                runner.experiment_id,
            )
            assert exp_row["final_status"] == "stopped"
            assert exp_row["is_complete"] is False

            persisted_seqs = {
                r["seq"]
                for r in await pool.fetch(
                    "SELECT seq FROM experiment_events WHERE experiment_id = $1",
                    runner.experiment_id,
                )
            }
            assert persisted_seqs == {0, 2}  # seq 1 is the real, honest gap
        finally:
            await _cleanup(pool, runner.experiment_id)
            await pool.close()

    asyncio.run(run())


def test_concurrent_experiments_are_isolated_by_experiment_id():
    async def run() -> None:
        pool = await create_pool(TEST_SETTINGS)
        runner_a = _make_runner(seed=1)
        runner_b = _make_runner(seed=2)
        try:
            writer_a = await _start_writer(pool, runner_a)
            writer_b = await _start_writer(pool, runner_b)
            await runner_a.publish_initial()
            await runner_b.publish_initial()

            await asyncio.gather(runner_a._run_loop(), runner_b._run_loop())

            await asyncio.gather(
                _wait_for_finalize(writer_a),
                _wait_for_finalize(writer_b),
            )

            for runner in (runner_a, runner_b):
                rows = await pool.fetch(
                    "SELECT seq FROM experiment_events WHERE experiment_id = $1 ORDER BY seq",
                    runner.experiment_id,
                )
                seqs = [r["seq"] for r in rows]
                assert seqs == list(range(runner._emitter.last_seq + 1))
        finally:
            await _cleanup(pool, runner_a.experiment_id)
            await _cleanup(pool, runner_b.experiment_id)
            await pool.close()

    asyncio.run(run())
