"""Second bus subscriber that persists the canonical live event stream to
Postgres (docs/SPEC.md:211: "Phase 1.5 adds a PostgresWriter as a second bus
subscriber. Nothing else changes."). Never generates, mutates, reorders, or
reinterprets events -- EventEmitter remains the sole seq assigner; this
module only writes what it's handed, in the order it's handed it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg

from app.events.version import SCHEMA_VERSION
from app.persistence.registry import writer_registry
from app.schemas.events import Event
from app.version import APP_VERSION

if TYPE_CHECKING:
    from app.events.bus import EventBus
    from app.orchestrator.runner import ExperimentRunner

logger = logging.getLogger(__name__)

# Non-blocking drain cap per batch -- bursty ticks coalesce into one insert;
# an unbounded drain could otherwise starve a very hot bus indefinitely.
DRAIN_BATCH_CAP = 500

_INSERT_EVENTS_SQL = """
    INSERT INTO experiment_events
        (experiment_id, seq, event_id, sim_tick, event_type, agent_id,
         source_agent_id, target_agent_id, risk_score, metadata,
         schema_version, wall_time)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12)
    ON CONFLICT (experiment_id, seq) DO NOTHING
"""


class PostgresWriter:
    """Subscribes to one runner's EventBus exactly like a WS client does and
    persists every event it observes, in order, best-effort. A DB outage
    never blocks or affects the live run -- `EventBus.publish()` uses
    non-blocking `put_nowait` and the runner's tick loop never awaits this
    writer's consumption.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        experiment_id: UUID,
        bus: EventBus,
        runner: ExperimentRunner,
    ) -> None:
        self._pool = pool
        self._experiment_id = experiment_id
        self._bus = bus
        self._runner = runner
        self._queue: asyncio.Queue[Event] | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Subscribes, then inserts the `experiments` row. Subscribing first
        is mandatory (matches ws.py's own discipline): a publish between
        runner construction and this call would otherwise be silently lost
        to persistence. If the insert fails, the subscription is torn back
        down immediately so a failed persistence init never leaves an
        orphaned queue registered on the bus forever.
        """
        self._queue = self._bus.subscribe()
        try:
            await self._insert_experiment_row()
        except Exception:
            self._bus.unsubscribe(self._queue)
            self._queue = None
            raise
        self._task = asyncio.create_task(self._drain_loop())

    async def cancel(self) -> None:
        """Best-effort teardown for app shutdown -- cancels the drain task
        and unsubscribes, without attempting a final write (the process is
        going down; whatever was already committed stands as the durable
        partial record)."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._queue is not None:
            self._bus.unsubscribe(self._queue)

    async def _insert_experiment_row(self) -> None:
        config = self._runner.config
        await self._pool.execute(
            """
            INSERT INTO experiments (experiment_id, seed, config, schema_version, app_version)
            VALUES ($1, $2, $3::jsonb, $4, $5)
            """,
            self._experiment_id,
            config.seed,
            config.model_dump_json(),
            SCHEMA_VERSION,
            APP_VERSION,
        )

    async def _drain_loop(self) -> None:
        assert self._queue is not None
        while True:
            get_task: asyncio.Task[Event] = asyncio.ensure_future(self._queue.get())
            term_task: asyncio.Task[bool] = asyncio.ensure_future(
                self._runner._terminal_event.wait()
            )
            done, pending = await asyncio.wait(
                {get_task, term_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.wait(pending)

            batch: list[Event] = []
            if get_task in done and not get_task.cancelled():
                batch.append(get_task.result())
            while len(batch) < DRAIN_BATCH_CAP:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            if batch:
                await self._write_batch(batch)

            # Terminal-signal-wins is necessary but not sufficient to
            # finalize: a queue holding more than DRAIN_BATCH_CAP events at
            # the moment terminal fires needs more than one drain pass. Only
            # finalize once the queue is verifiably empty -- otherwise loop
            # back for another bounded drain (the terminal event stays set,
            # so every subsequent iteration's term_task resolves instantly;
            # no more events can ever be added past this point, by
            # construction of where the runner sets it).
            if term_task in done and self._queue.empty():
                await self._finalize()
                return

    async def _write_batch(self, events: Sequence[Event]) -> None:
        rows = [
            (
                self._experiment_id,
                e.seq,
                e.event_id,
                e.sim_tick,
                e.event_type,
                e.agent_id,
                e.source_agent_id,
                e.target_agent_id,
                e.risk_score,
                json.dumps(e.metadata),
                e.schema_version,
                e.wall_time,
            )
            for e in events
        ]
        try:
            async with self._pool.acquire() as conn, conn.transaction():
                await conn.executemany(_INSERT_EVENTS_SQL, rows)
        except Exception:
            # Best-effort, fire-and-forget (docs/PHASE_1_5_PLAN.md §11): a
            # failed batch is logged and skipped rather than retried against
            # a possibly-down DB while the live simulation keeps producing
            # more events. The resulting seq gap is caught, not hidden, by
            # _finalize()'s contiguity check.
            logger.exception(
                "failed to persist event batch for experiment %s", self._experiment_id
            )

    async def _finalize(self) -> None:
        summary = self._runner.summary()
        try:
            row = await self._pool.fetchrow(
                "SELECT count(*) AS cnt, min(seq) AS lo, max(seq) AS hi "
                "FROM experiment_events WHERE experiment_id = $1",
                self._experiment_id,
            )
            # Provable, not inferred: completeness is a contiguous
            # [0, final_last_seq] range with no gaps, checked against what
            # actually landed in experiment_events -- not trusted from
            # final_status or from an in-memory "did a write fail" flag,
            # either of which could be wrong if the process restarted or a
            # failure happened after this writer instance's own bookkeeping.
            is_complete = (
                row is not None
                and row["cnt"] == summary.last_seq + 1
                and row["lo"] == 0
                and row["hi"] == summary.last_seq
            )
            await self._pool.execute(
                """
                UPDATE experiments
                SET final_status = $1, final_sim_tick = $2, final_last_seq = $3,
                    is_complete = $4, completed_at = now()
                WHERE experiment_id = $5
                """,
                summary.status,
                summary.sim_tick,
                summary.last_seq,
                is_complete,
                self._experiment_id,
            )
        except Exception:
            # final_status stays NULL -- indistinguishable from a crash from
            # the reader's perspective, an acceptable conservative
            # degradation rather than silently wrong data.
            logger.exception("failed to finalize experiment %s", self._experiment_id)
        finally:
            if self._queue is not None:
                self._bus.unsubscribe(self._queue)
            writer_registry.remove(self._experiment_id)
