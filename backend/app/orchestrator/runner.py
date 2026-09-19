import asyncio
from typing import Literal
from uuid import UUID, uuid4

from app.engine.propagation import is_finished
from app.engine.tick import advance
from app.engine.topology import build_world
from app.events.bus import EventBus
from app.events.emitter import EventEmitter
from app.gateway.gateway import ModelGateway
from app.scenarios.registry import run_async_scenarios
from app.schemas.events import EventDraft, EventType
from app.schemas.experiment import EdgeView, ExperimentConfig, ExperimentSummary, NodeView
from app.schemas.frames import SnapshotFrame

Status = Literal["running", "paused", "finished", "stopped"]


class InvalidTransitionError(Exception):
    """Raised when a control operation is invalid for the runner's current status."""


class ExperimentRunner:
    """The only place wall-clock time exists."""

    tick_interval_default = 0.25

    def __init__(self, config: ExperimentConfig, gateway: ModelGateway | None = None) -> None:
        self.experiment_id: UUID = uuid4()
        self.config = config
        self.bus = EventBus()
        self._emitter = EventEmitter(self.experiment_id)
        # Phase 2 (docs/PHASE_2_PLAN.md §2, §7): None unless the caller built
        # one (routes_experiments.py, only when real_agent_count > 0) --
        # real_agent_step is only ever called when this is set, so every
        # existing test/call site constructing ExperimentRunner(config) with
        # no gateway is completely unaffected.
        self._gateway = gateway
        self.status: Status = "running"
        self.state, topology_drafts = build_world(config)
        self._running = True
        self._task: asyncio.Task[None] | None = None
        self.tick_interval: float = self.tick_interval_default
        self._speed: float = 1.0
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        # Set only *after* the terminal event has actually been published --
        # in _run_loop's natural-finish path, and at the very end of stop(),
        # after `await self.bus.publish(...)` completes -- never before. A
        # persistence writer races this against its queue to know when it's
        # safe to drain the last of the queue and finalize without risking
        # finalizing one event early (docs/PHASE_1_5_PLAN.md §6).
        self._terminal_event = asyncio.Event()
        self._initial_drafts: list[EventDraft] = [
            EventDraft(sim_tick=0, event_type=EventType.EXPERIMENT_STARTED),
            *topology_drafts,
        ]

    async def publish_initial(self) -> None:
        """Awaited synchronously by the create-experiment route before it
        returns, so a client that immediately opens the WS is guaranteed to
        find these events already in the bus buffer — no start-up race."""
        events = self._emitter.emit(self._initial_drafts)
        await self.bus.publish(events)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run_loop())

    def pause(self) -> None:
        if self.status == "paused":
            return
        if self.status != "running":
            raise InvalidTransitionError(f"cannot pause an experiment with status {self.status!r}")
        self._pause_event.clear()
        self.status = "paused"

    def resume(self) -> None:
        if self.status == "running":
            return
        if self.status != "paused":
            raise InvalidTransitionError(f"cannot resume an experiment with status {self.status!r}")
        self.status = "running"
        self._pause_event.set()

    def set_speed(self, multiplier: float) -> None:
        if self.status in ("finished", "stopped"):
            raise InvalidTransitionError(
                f"cannot change speed of an experiment with status {self.status!r}"
            )
        self._speed = max(0.25, min(8.0, multiplier))

    async def _run_loop(self) -> None:
        while self._running and not is_finished(self.state, self.config):
            await self._pause_event.wait()
            if not self._running:
                break
            self.state, drafts = advance(self.state, self.config)
            if self._gateway is not None:
                # Runs after advance()'s propagation+detection, not
                # interleaved between them -- a real agent compromised this
                # tick is first eligible for quarantine detection next tick,
                # a deliberate, documented one-tick timing difference from
                # the simulated path (docs/PHASE_2_PLAN.md §2, §16).
                self.state, real_drafts = await run_async_scenarios(
                    self.state, self.config, self._gateway, tick=self.state.tick
                )
                drafts = [*drafts, *real_drafts]
            events = self._emitter.emit(drafts)
            await self.bus.publish(events)
            await asyncio.sleep(self.tick_interval / self._speed)
        if self._running:
            self.status = "finished"
            self._terminal_event.set()
        self._task = None

    async def stop(self) -> None:
        if self.status == "finished":
            return
        if self.status == "stopped":
            task = self._task
            if task is not None:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            return
        self._running = False
        self.status = "stopped"
        task = self._task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            if self._task is task:
                self._task = None
        events = self._emitter.emit(
            [EventDraft(sim_tick=self.state.tick, event_type=EventType.EXPERIMENT_STOPPED)]
        )
        await self.bus.publish(events)
        self._terminal_event.set()

    def summary(self) -> ExperimentSummary:
        return ExperimentSummary(
            experiment_id=self.experiment_id,
            status=self.status,
            sim_tick=self.state.tick,
            last_seq=self._emitter.last_seq,
            config=self.config,
        )

    def snapshot(self) -> SnapshotFrame:
        return SnapshotFrame(
            experiment_id=self.experiment_id,
            last_seq=self._emitter.last_seq,
            sim_tick=self.state.tick,
            status=self.status,
            nodes=[
                NodeView(
                    id=n.id,
                    software_type=n.software_type,
                    security_state=n.security_state,
                    compromised_by=n.compromised_by,
                    tick_compromised=n.tick_compromised,
                    agent_kind=n.agent_kind,
                )
                for n in self.state.nodes.values()
            ],
            edges=[EdgeView(source=a, target=b) for a, b in self.state.edges],
        )
