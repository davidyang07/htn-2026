"""The live runtime session: workers, artifacts, quarantine, tainting.

Deliberately not an ``ExperimentRunner`` (docs/ARCHITECTURE.md §6). That class
owns a wall-clock tick loop over a generated ``WorldState`` of >= 25 synthetic
nodes with a patient-zero compromise seeded at tick 0. A live session has no
ticks -- it advances only when the external workflow calls in -- starts
entirely healthy, and has about five named workers.

What it reuses unchanged: ``EventEmitter`` (the sole assigner of ``seq``, one
per session), ``EventBus`` (fan-out plus a 2000-event ring buffer), the
``Event``/``EventDraft`` schema, the ``SnapshotFrame``/``EventFrame`` protocol,
and ``app/engine/state.py::SecurityState``. There is no second security-state
vocabulary: the frontend's severity map is keyed on those exact values.
"""

import uuid
from dataclasses import dataclass, field
from typing import Literal

from app.engine.state import SecurityState
from app.events.bus import EventBus
from app.events.emitter import EventEmitter
from app.runtime.policy import Decision, evaluate
from app.schemas.events import Event, EventDraft, EventType
from app.schemas.experiment import EdgeView, NodeView
from app.schemas.frames import SnapshotFrame

WorkflowState = Literal[
    "idle",
    "running",
    "under_attack",
    "recovering",
    "recovered",
    "failed",
]

#: The live workflow's own state machine mapped onto the four values the
#: existing SnapshotFrame protocol allows. Reusing that protocol is what lets
#: the frontend's pure `reduce()` drive the /demo screen unchanged.
_FRAME_STATUS: dict[WorkflowState, Literal["running", "paused", "finished", "stopped"]] = {
    "idle": "paused",
    "running": "running",
    "under_attack": "running",
    "recovering": "running",
    "recovered": "finished",
    "failed": "stopped",
}


@dataclass
class WorkerNode:
    """One real WorkSwarm worker, as AgentShield sees it."""

    id: str
    role: str
    security_state: SecurityState = SecurityState.HEALTHY
    current_task: str | None = None
    #: Worker ids this one receives work from -- the collaboration edges.
    upstream: tuple[str, ...] = ()
    #: Set on a replacement worker; the id of the worker it took over from.
    replaces: str | None = None
    #: Whether this worker's decisions came from a real model call. Recorded
    #: honestly so the UI never implies an LLM ran when none was configured.
    model_backed: bool = False
    step_registered: int = 0
    step_quarantined: int | None = None
    quarantine_reason: str | None = None
    #: What compromised it -- the poisoned artifact, for the demo's researcher.
    compromised_by: str | None = None

    @property
    def is_active(self) -> bool:
        return self.security_state not in (SecurityState.QUARANTINED,)


@dataclass
class Artifact:
    """A worker's output. Trust is a property of the artifact, not the worker,
    because it is the artifact that propagates."""

    id: str
    worker_id: str
    kind: str
    summary: str
    trusted: bool = True
    taint_reason: str | None = None
    step: int = 0


@dataclass
class ResourceGrant:
    """The result of one resource request, before any content is fetched."""

    decision: Decision
    quarantined: bool
    recovery_required: bool
    events: list[Event] = field(default_factory=list)


class UnknownWorkerError(Exception):
    """A call named a worker this session has never registered."""


class LiveRuntimeSession:
    """One live workflow under AgentShield's protection.

    Every mutating method is ``async`` and does three things in one place:
    mutate state, emit through this session's single ``EventEmitter``, and
    publish to this session's ``EventBus``. Keeping it in one place is what
    guarantees the ordering contract -- ``EventEmitter`` is the sole assigner
    of ``seq``, and there is exactly one per session (docs/SPEC.md §1).
    """

    def __init__(self, objective: str, session_id: uuid.UUID | None = None) -> None:
        self.session_id = session_id or uuid.uuid4()
        self.objective = objective
        self.bus = EventBus()
        self._emitter = EventEmitter(self.session_id)
        self.workers: dict[str, WorkerNode] = {}
        self.artifacts: dict[str, Artifact] = {}
        self.workflow_state: WorkflowState = "idle"
        #: A monotonic workflow-step counter. It occupies the `sim_tick` field
        #: so that field keeps a coherent meaning on the shared frame protocol
        #: (docs/ARCHITECTURE.md §6) -- "how far through the workflow", not
        #: "which engine tick".
        self.step = 0
        self.attack_detected = False
        self.recovery_required = False
        #: The real `pytest demo_target` summary line, verbatim. Never
        #: fabricated -- absent until a run actually reports one.
        self.test_summary: str | None = None
        self.tests_passed: bool | None = None
        #: How many real model calls this run made. Zero means every worker
        #: ran as a deterministic stand-in.
        self.model_calls = 0

    # --- emission ---------------------------------------------------------

    @property
    def last_seq(self) -> int:
        return self._emitter.last_seq

    async def _publish(self, drafts: list[EventDraft]) -> list[Event]:
        events = self._emitter.emit(drafts)
        await self.bus.publish(events)
        return events

    def _draft(
        self,
        event_type: EventType,
        *,
        agent_id: str | None = None,
        source_agent_id: str | None = None,
        target_agent_id: str | None = None,
        risk_score: float | None = None,
        **metadata: object,
    ) -> EventDraft:
        return EventDraft(
            sim_tick=self.step,
            event_type=event_type,
            agent_id=agent_id,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            risk_score=risk_score,
            metadata=metadata,  # type: ignore[arg-type]
        )

    def _worker(self, worker_id: str) -> WorkerNode:
        worker = self.workers.get(worker_id)
        if worker is None:
            raise UnknownWorkerError(worker_id)
        return worker

    # --- registration and lifecycle --------------------------------------

    async def register_worker(
        self,
        worker_id: str,
        role: str,
        *,
        upstream: tuple[str, ...] = (),
        replaces: str | None = None,
        model_backed: bool = False,
    ) -> list[Event]:
        self.step += 1
        worker = WorkerNode(
            id=worker_id,
            role=role,
            upstream=upstream,
            replaces=replaces,
            model_backed=model_backed,
            step_registered=self.step,
        )
        self.workers[worker_id] = worker

        metadata: dict[str, object] = {"role": role, "model_backed": model_backed}
        if replaces is not None:
            metadata["replaces"] = replaces
        return await self._publish(
            [self._draft(EventType.AGENT_CREATED, agent_id=worker_id, **metadata)]
        )

    async def start_worker(self, worker_id: str, task: str) -> list[Event]:
        worker = self._worker(worker_id)
        if not worker.is_active:
            raise UnknownWorkerError(f"{worker_id} is quarantined and cannot be started")
        self.step += 1
        worker.current_task = task
        if self.workflow_state == "idle":
            self.workflow_state = "running"
        return await self._publish(
            [
                self._draft(EventType.TASK_ASSIGNED, agent_id=worker_id, task=task),
                self._draft(EventType.AGENT_STARTED, agent_id=worker_id, task=task),
            ]
        )

    async def complete_task(
        self,
        worker_id: str,
        *,
        step_name: str,
        detail: str,
        **metadata: object,
    ) -> list[Event]:
        """Record a finished unit of work. ``step_name`` is the discriminator
        the demo reads: "analysis" | "patch" | "pytest" | "review"."""
        worker = self._worker(worker_id)
        if not worker.is_active:
            raise UnknownWorkerError(f"{worker_id} is quarantined; its work is not accepted")
        self.step += 1
        worker.current_task = None
        return await self._publish(
            [
                self._draft(
                    EventType.TASK_COMPLETED,
                    agent_id=worker_id,
                    step=step_name,
                    detail=detail,
                    **metadata,
                )
            ]
        )

    async def record_model_call(
        self,
        worker_id: str,
        *,
        provider: str,
        model: str,
        endpoint_host: str,
        latency_ms: int,
        prompt_chars: int,
        response_chars: int,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> list[Event]:
        """Record that a worker's reasoning came from a real model call.

        Metadata is identity and size only -- never a prompt, a completion or
        a credential. A worker that ran as a deterministic stand-in records
        nothing here, which is exactly what makes the presence of these events
        evidence rather than decoration.
        """
        worker = self._worker(worker_id)
        self.step += 1
        worker.model_backed = True
        self.model_calls += 1

        metadata: dict[str, object] = {
            "provider": provider,
            "model": model,
            "endpoint_host": endpoint_host,
            "latency_ms": latency_ms,
            "prompt_chars": prompt_chars,
            "response_chars": response_chars,
        }
        if prompt_tokens is not None:
            metadata["prompt_tokens"] = prompt_tokens
        if completion_tokens is not None:
            metadata["completion_tokens"] = completion_tokens

        return await self._publish(
            [
                self._draft(EventType.MODEL_REQUESTED, agent_id=worker_id, **metadata),
                self._draft(EventType.MODEL_RESPONDED, agent_id=worker_id, **metadata),
            ]
        )

    # --- artifacts and trust ---------------------------------------------

    def record_artifact(
        self, artifact_id: str, worker_id: str, kind: str, summary: str
    ) -> Artifact:
        """Register a worker's output. Emits nothing -- an artifact becomes
        interesting only when it is tainted or consumed."""
        worker = self._worker(worker_id)
        artifact = Artifact(
            id=artifact_id,
            worker_id=worker_id,
            kind=kind,
            summary=summary,
            trusted=worker.is_active,
            taint_reason=None if worker.is_active else worker.quarantine_reason,
            step=self.step,
        )
        self.artifacts[artifact_id] = artifact
        return artifact

    def taint_artifacts_of(self, worker_id: str, reason: str) -> list[Artifact]:
        tainted: list[Artifact] = []
        for artifact in self.artifacts.values():
            if artifact.worker_id == worker_id and artifact.trusted:
                artifact.trusted = False
                artifact.taint_reason = reason
                tainted.append(artifact)
        return tainted

    def trusted_context_for(self, worker_id: str) -> list[Artifact]:
        """The artifacts a worker may be seeded with: everything still
        trusted, produced by somebody else. A tainted artifact is excluded
        here and nowhere else, so there is exactly one place this can go
        wrong."""
        return [
            artifact
            for artifact in self.artifacts.values()
            if artifact.trusted and artifact.worker_id != worker_id
        ]

    # --- the decision -----------------------------------------------------

    async def request_resource(self, worker_id: str, resource_path: str) -> ResourceGrant:
        """THE synchronous policy decision.

        Nothing is read here. The caller fetches content only after this
        returns an allow, and only for ``decision.normalized_path``.
        """
        worker = self._worker(worker_id)
        self.step += 1

        drafts: list[EventDraft] = [
            self._draft(
                EventType.TOOL_REQUESTED,
                agent_id=worker_id,
                tool="resource_read",
                resource=resource_path,
            )
        ]

        # A quarantined worker is removed from the team. Its requests are
        # refused regardless of path -- including paths that would otherwise
        # be perfectly ordinary.
        if not worker.is_active:
            drafts.append(
                self._draft(
                    EventType.TOOL_DENIED,
                    agent_id=worker_id,
                    tool="resource_read",
                    resource=resource_path,
                    violation_type="quarantined_worker",
                    reason="Worker is quarantined; it can take no further action.",
                )
            )
            events = await self._publish(drafts)
            return ResourceGrant(
                decision=Decision(
                    allowed=False,
                    rule="quarantined_worker",  # type: ignore[arg-type]
                    reason="Worker is quarantined; it can take no further action.",
                    normalized_path=None,
                ),
                quarantined=True,
                recovery_required=self.recovery_required,
                events=events,
            )

        decision = evaluate(resource_path)

        if decision.allowed:
            drafts.append(
                self._draft(
                    EventType.TOOL_EXECUTED,
                    agent_id=worker_id,
                    tool="resource_read",
                    resource=decision.normalized_path,
                )
            )
            events = await self._publish(drafts)
            return ResourceGrant(
                decision=decision,
                quarantined=False,
                recovery_required=self.recovery_required,
                events=events,
            )

        # The deny cascade. Every one of these is emitted before the HTTP
        # response is written, and the secret is not read at any point in it.
        drafts.append(
            self._draft(
                EventType.TOOL_DENIED,
                agent_id=worker_id,
                tool="resource_read",
                resource=resource_path,
                violation_type=decision.rule,
                reason=decision.reason,
            )
        )
        drafts.append(
            self._draft(
                EventType.POLICY_VIOLATION,
                agent_id=worker_id,
                risk_score=1.0,
                violation_type=decision.rule,
                resource=resource_path,
                reason=decision.reason,
            )
        )
        drafts.append(
            self._draft(
                EventType.ANOMALY_DETECTED,
                agent_id=worker_id,
                risk_score=1.0,
                violation_type=decision.rule,
                detector="deterministic_path_policy",
                reason=(
                    f"{worker.role} requested a resource outside its policy envelope "
                    "immediately after reading untrusted repository documentation."
                ),
            )
        )

        quarantine_drafts = self._quarantine_drafts(
            worker,
            reason=decision.reason,
            violation_type=decision.rule,
            compromised_by="demo_target/docs/auth_notes.md",
        )
        events = await self._publish(drafts + quarantine_drafts)
        return ResourceGrant(
            decision=decision,
            quarantined=True,
            recovery_required=True,
            events=events,
        )

    def _quarantine_drafts(
        self,
        worker: WorkerNode,
        *,
        reason: str,
        violation_type: str,
        compromised_by: str | None = None,
    ) -> list[EventDraft]:
        """Mutates the worker and returns the drafts. Never emits -- the
        caller publishes one batch so the cascade cannot be interleaved."""
        worker.security_state = SecurityState.QUARANTINED
        worker.step_quarantined = self.step
        worker.quarantine_reason = reason
        worker.compromised_by = compromised_by
        worker.current_task = None

        tainted = self.taint_artifacts_of(
            worker.id, f"Produced by a quarantined worker ({violation_type})."
        )

        self.attack_detected = True
        self.recovery_required = True
        self.workflow_state = "under_attack"

        return [
            self._draft(
                EventType.AGENT_QUARANTINED,
                agent_id=worker.id,
                legitimate=True,
                violation_type=violation_type,
                reason=reason,
                tainted_artifacts=[a.id for a in tainted],
                recovery_required=True,
            )
        ]

    async def quarantine(
        self, worker_id: str, *, reason: str, violation_type: str
    ) -> list[Event]:
        """Quarantine a worker outside the resource-request path."""
        worker = self._worker(worker_id)
        if not worker.is_active:
            return []
        self.step += 1
        return await self._publish(
            self._quarantine_drafts(worker, reason=reason, violation_type=violation_type)
        )

    # --- recovery ---------------------------------------------------------

    async def reassign(
        self,
        *,
        from_worker_id: str,
        to_worker_id: str,
        role: str,
        task: str,
        upstream: tuple[str, ...] = (),
        model_backed: bool = False,
    ) -> list[Event]:
        """Hand a quarantined worker's task to a brand-new replacement.

        The replacement is a genuinely new worker with its own identity. It is
        seeded from ``trusted_context_for()`` and nothing else -- the caller is
        responsible for that, and ``assert_context_is_trusted`` exists so it
        can prove it.
        """
        quarantined = self._worker(from_worker_id)
        self.step += 1
        self.workflow_state = "recovering"

        replacement = WorkerNode(
            id=to_worker_id,
            role=role,
            upstream=upstream,
            replaces=from_worker_id,
            model_backed=model_backed,
            step_registered=self.step,
            current_task=task,
        )
        self.workers[to_worker_id] = replacement
        self.recovery_required = False

        return await self._publish(
            [
                self._draft(
                    EventType.TASK_REASSIGNED,
                    agent_id=from_worker_id,
                    source_agent_id=from_worker_id,
                    target_agent_id=to_worker_id,
                    task=task,
                    reason=quarantined.quarantine_reason or "Worker quarantined.",
                ),
                self._draft(
                    EventType.AGENT_CREATED,
                    agent_id=to_worker_id,
                    role=role,
                    replaces=from_worker_id,
                    model_backed=model_backed,
                    trusted_context=[a.id for a in self.trusted_context_for(to_worker_id)],
                ),
                self._draft(
                    EventType.AGENT_STARTED,
                    agent_id=to_worker_id,
                    task=task,
                    context_policy="trusted_artifacts_only",
                ),
            ]
        )

    def assert_context_is_trusted(self, artifact_ids: list[str]) -> None:
        """Raise if any named artifact is tainted or unknown.

        The replacement worker's whole value is that the poisoned context did
        not reach it. This is where that is checked, not asserted in prose.
        """
        for artifact_id in artifact_ids:
            artifact = self.artifacts.get(artifact_id)
            if artifact is None:
                raise ValueError(f"unknown artifact {artifact_id!r} in replacement context")
            if not artifact.trusted:
                raise ValueError(
                    f"tainted artifact {artifact_id!r} would reach a replacement worker"
                )

    async def record_test_run(
        self, worker_id: str, *, passed: bool, summary: str, exit_code: int, command: str
    ) -> list[Event]:
        """Record a real test run. A red run is recorded red."""
        self.test_summary = summary
        self.tests_passed = passed
        return await self.complete_task(
            worker_id,
            step_name="pytest",
            detail=summary,
            passed=passed,
            exit_code=exit_code,
            command=command,
        )

    async def recover(self, *, summary: str) -> list[Event]:
        """The workflow finished despite the compromise."""
        self.step += 1
        self.workflow_state = "recovered"
        self.recovery_required = False

        drafts: list[EventDraft] = []
        for worker in self.workers.values():
            if worker.replaces is not None and worker.is_active:
                worker.security_state = SecurityState.RECOVERED
                drafts.append(
                    self._draft(
                        EventType.AGENT_RECOVERED,
                        agent_id=worker.id,
                        replaces=worker.replaces,
                    )
                )

        drafts.append(
            self._draft(
                EventType.WORKFLOW_RECOVERED,
                summary=summary,
                attack_detected=self.attack_detected,
                quarantined=[
                    w.id
                    for w in self.workers.values()
                    if w.security_state == SecurityState.QUARANTINED
                ],
                tests_passed=self.tests_passed,
                test_summary=self.test_summary,
            )
        )
        return await self._publish(drafts)

    async def fail(self, *, reason: str) -> list[Event]:
        """The workflow could not finish. Reported honestly, not as a recovery."""
        self.step += 1
        self.workflow_state = "failed"
        return await self._publish(
            [self._draft(EventType.EXPERIMENT_STOPPED, reason=reason, recovered=False)]
        )

    # --- views ------------------------------------------------------------

    def nodes(self) -> list[NodeView]:
        return [
            NodeView(
                id=worker.id,
                software_type=worker.role,
                security_state=worker.security_state,
                compromised_by=worker.compromised_by,
                tick_compromised=worker.step_quarantined,
                agent_kind="real",
            )
            for worker in self.workers.values()
        ]

    def edges(self) -> list[EdgeView]:
        seen: set[tuple[str, str]] = set()
        edges: list[EdgeView] = []

        def add(source: str, target: str) -> None:
            if source not in self.workers or target not in self.workers:
                return
            key = (source, target)
            if key in seen:
                return
            seen.add(key)
            edges.append(EdgeView(source=source, target=target))

        for worker in self.workers.values():
            for upstream_id in worker.upstream:
                add(upstream_id, worker.id)

        # A replacement inherits the handoffs of the worker it took over from,
        # so the graph shows the team routing around the quarantined node
        # rather than leaving the replacement dangling. Downstream workers
        # registered their upstream once, at creation, and cannot re-declare
        # it later -- this is where the recovery becomes visible.
        for worker in self.workers.values():
            if worker.replaces is None:
                continue
            for other in self.workers.values():
                if worker.replaces in other.upstream:
                    add(worker.id, other.id)

        return edges

    def snapshot(self) -> SnapshotFrame:
        return SnapshotFrame(
            experiment_id=self.session_id,
            last_seq=self.last_seq,
            sim_tick=self.step,
            status=_FRAME_STATUS[self.workflow_state],
            nodes=self.nodes(),
            edges=self.edges(),
        )
