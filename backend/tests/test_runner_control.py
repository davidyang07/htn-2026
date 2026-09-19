import asyncio

from app.orchestrator.runner import ExperimentRunner
from app.schemas.events import Event, EventType
from app.schemas.experiment import ExperimentConfig


def _make_runner(**overrides) -> ExperimentRunner:
    config = ExperimentConfig(seed=42, node_count=25, max_ticks=10, **overrides)
    runner = ExperimentRunner(config)
    runner.tick_interval = 0
    return runner


async def _drive_to_finished(runner: ExperimentRunner) -> None:
    await runner.publish_initial()
    await runner._run_loop()


def test_pause_freezes_tick_progression():
    async def run() -> None:
        runner = _make_runner()
        await runner.publish_initial()
        task = asyncio.create_task(runner._run_loop())

        await asyncio.sleep(0)
        runner.pause()
        frozen_tick = runner.state.tick
        for _ in range(5):
            await asyncio.sleep(0)
            assert runner.state.tick == frozen_tick

        runner.resume()
        await task

    asyncio.run(run())


def test_resume_continues_from_exact_suspended_state():
    async def run() -> None:
        runner = _make_runner()
        await runner.publish_initial()
        task = asyncio.create_task(runner._run_loop())

        await asyncio.sleep(0)
        runner.pause()
        frozen_tick = runner.state.tick

        runner.resume()
        await asyncio.sleep(0)
        assert runner.state.tick >= frozen_tick
        await task

    asyncio.run(run())


def test_stop_while_running_clears_task_and_settles():
    async def run() -> None:
        runner = _make_runner()
        await runner.publish_initial()
        runner.start()
        task = runner._task
        await asyncio.sleep(0)

        await runner.stop()

        assert runner._task is None
        assert task is not None
        assert task.cancelled() or task.done()

    asyncio.run(run())


def test_stop_while_paused_clears_task_and_settles():
    async def run() -> None:
        runner = _make_runner()
        await runner.publish_initial()
        runner.start()
        task = runner._task
        await asyncio.sleep(0)
        runner.pause()

        await runner.stop()

        assert runner._task is None
        assert task is not None
        assert task.cancelled() or task.done()

    asyncio.run(run())


def test_stop_called_twice_emits_exactly_one_stopped_event():
    async def run() -> None:
        runner = _make_runner()
        await runner.publish_initial()
        runner.start()
        await asyncio.sleep(0)

        await runner.stop()
        await runner.stop()

        events = runner.bus.since(-1)
        stopped = [e for e in events if e.event_type == EventType.EXPERIMENT_STOPPED]
        assert len(stopped) == 1

    asyncio.run(run())


def test_stop_on_naturally_finished_runner_is_noop():
    async def run() -> None:
        runner = _make_runner()
        await _drive_to_finished(runner)
        assert runner.status == "finished"
        assert runner._task is None

        await runner.stop()

        assert runner.status == "finished"
        assert runner._task is None

    asyncio.run(run())


def test_concurrent_stop_calls_emit_exactly_one_stopped_event():
    async def run() -> None:
        runner = _make_runner()
        await runner.publish_initial()
        runner.start()
        await asyncio.sleep(0)

        results = await asyncio.gather(
            runner.stop(), runner.stop(), return_exceptions=True
        )
        for r in results:
            assert not isinstance(r, Exception)

        events = runner.bus.since(-1)
        stopped = [e for e in events if e.event_type == EventType.EXPERIMENT_STOPPED]
        assert len(stopped) == 1
        assert runner._task is None

    asyncio.run(run())


def test_summary_last_seq_matches_emitter():
    async def run() -> None:
        runner = _make_runner()
        await runner.publish_initial()
        assert runner.summary().last_seq == runner._emitter.last_seq
        await runner._run_loop()
        assert runner.summary().last_seq == runner._emitter.last_seq

    asyncio.run(run())


def test_snapshot_carries_compromise_provenance_for_every_node():
    """Regression: snapshot() once built NodeView with only id/software_type/
    security_state, silently dropping compromised_by/tick_compromised even
    though AgentNode carries them — breaking the agent detail drawer's
    ground truth on every fresh connect, not just on reconnect
    (M1_PLAN.md §9: NodeView exists precisely so a snapshot alone is enough)."""

    async def run() -> None:
        runner = _make_runner(p_same=1.0, p_cross=1.0, detector_sensitivity=0.0)
        await _drive_to_finished(runner)

        seed_nodes = [
            n
            for n in runner.state.nodes.values()
            if n.security_state != "healthy" and n.compromised_by is None
        ]
        assert len(seed_nodes) == 1
        seed = seed_nodes[0]
        assert seed.tick_compromised == 0

        propagated = [n for n in runner.state.nodes.values() if n.compromised_by is not None]
        assert propagated, "expected propagation beyond the seed node"

        by_id = {n.id: n for n in runner.snapshot().nodes}

        seed_view = by_id[seed.id]
        assert seed_view.compromised_by is None
        assert seed_view.tick_compromised == 0

        for node in propagated:
            view = by_id[node.id]
            assert view.compromised_by == node.compromised_by
            assert view.tick_compromised == node.tick_compromised

    asyncio.run(run())


def test_every_concurrent_stop_waits_for_task_settlement():
    async def run() -> None:
        runner = _make_runner()
        cancellation_started = asyncio.Event()
        allow_settlement = asyncio.Event()

        async def slow_to_settle_after_cancellation() -> None:
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancellation_started.set()
                await allow_settlement.wait()
                raise

        task = asyncio.create_task(slow_to_settle_after_cancellation())
        runner._task = task
        await asyncio.sleep(0)

        first_stop = asyncio.create_task(runner.stop())
        await cancellation_started.wait()
        second_stop = asyncio.create_task(runner.stop())
        await asyncio.sleep(0)

        assert not second_stop.done()
        assert not task.done()

        allow_settlement.set()
        await asyncio.gather(first_stop, second_stop)

        assert task.done()
        assert runner._task is None

    asyncio.run(run())


def test_terminal_event_not_set_while_running():
    runner = _make_runner()
    assert not runner._terminal_event.is_set()


def test_terminal_event_set_on_natural_completion():
    async def run() -> None:
        runner = _make_runner()
        await _drive_to_finished(runner)
        assert runner.status == "finished"
        assert runner._terminal_event.is_set()

    asyncio.run(run())


def test_terminal_event_is_set_only_after_stop_publishes_the_final_event():
    """Regression for the verified race in docs/PHASE_1_5_PLAN.md §6:
    `stop()` must publish EXPERIMENT_STOPPED *before* signalling terminal, not
    after -- a persistence writer finalizing on "status terminal + queue
    empty" would otherwise risk observing the terminal signal before the
    final event has actually reached its queue and dropping it."""

    async def run() -> None:
        runner = _make_runner()
        await runner.publish_initial()
        runner.start()
        await asyncio.sleep(0)

        assert not runner._terminal_event.is_set()

        original_publish = runner.bus.publish
        observed_set_during_publish: bool | None = None

        async def spying_publish(events: list[Event]) -> None:
            nonlocal observed_set_during_publish
            await original_publish(events)
            if any(e.event_type == EventType.EXPERIMENT_STOPPED for e in events):
                observed_set_during_publish = runner._terminal_event.is_set()

        runner.bus.publish = spying_publish  # type: ignore[method-assign]

        await runner.stop()

        assert observed_set_during_publish is False
        assert runner._terminal_event.is_set()

    asyncio.run(run())
