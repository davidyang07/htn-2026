"""HTTP + WebSocket for the AgentShield live runtime (docs/MVP_PLAN.md P0.4).

One direction only: the WorkSwarm SwarmFlow calls in; AgentShield never calls
out to WorkSwarm. `resource-request` is a *synchronous decision endpoint*, not
a fire-and-forget log -- its response body is what the workflow obeys, and the
full deny cascade is emitted before that response is written.

Kept entirely separate from `routes_experiments.py` and the simulator's
registry: a live session is not an ExperimentRunner (docs/ARCHITECTURE.md §6).
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.runtime.explain import explain_incident
from app.runtime.registry import runtime_registry
from app.runtime.resources import (
    PolicyBypassError,
    ResourceAccessError,
    read_sandbox_resource,
)
from app.runtime.session import LiveRuntimeSession, UnknownWorkerError
from app.schemas.frames import EventFrame, SnapshotFrame
from app.schemas.runtime import (
    ArtifactRequest,
    ArtifactView,
    FailRequest,
    IncidentExplanation,
    ModelCallRequest,
    ReassignRequest,
    RecoverRequest,
    ResourceDecision,
    ResourceRequest,
    RuntimeEventPage,
    RuntimeResetResponse,
    RuntimeSessionSummary,
    SessionCreateRequest,
    TaskCompleteRequest,
    TaskStartRequest,
    TestRunRequest,
    WorkerRegistrationRequest,
    WorkerView,
)
from app.telemetry import sentry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


# --- helpers --------------------------------------------------------------


def _summary(session: LiveRuntimeSession) -> RuntimeSessionSummary:
    return RuntimeSessionSummary(
        session_id=session.session_id,
        objective=session.objective,
        workflow_state=session.workflow_state,
        step=session.step,
        last_seq=session.last_seq,
        attack_detected=session.attack_detected,
        recovery_required=session.recovery_required,
        model_calls=session.model_calls,
        tests_passed=session.tests_passed,
        test_summary=session.test_summary,
        workers=[
            WorkerView(
                id=worker.id,
                role=worker.role,
                security_state=worker.security_state,
                current_task=worker.current_task,
                upstream=list(worker.upstream),
                replaces=worker.replaces,
                model_backed=worker.model_backed,
                quarantine_reason=worker.quarantine_reason,
                step_quarantined=worker.step_quarantined,
            )
            for worker in session.workers.values()
        ],
        artifacts=[
            ArtifactView(
                id=artifact.id,
                worker_id=artifact.worker_id,
                kind=artifact.kind,
                summary=artifact.summary,
                trusted=artifact.trusted,
                taint_reason=artifact.taint_reason,
            )
            for artifact in session.artifacts.values()
        ],
    )


def _require(session_id: UUID) -> LiveRuntimeSession:
    session = runtime_registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown runtime session")
    return session


def _worker_call(session: LiveRuntimeSession, worker_id: str) -> None:
    if worker_id not in session.workers:
        raise HTTPException(status_code=404, detail=f"unknown worker {worker_id!r}")


# --- session lifecycle ----------------------------------------------------


@router.post(
    "/sessions",
    response_model=RuntimeSessionSummary,
    status_code=201,
)
async def create_session(body: SessionCreateRequest) -> RuntimeSessionSummary:
    if body.reset:
        runtime_registry.clear()

    session = LiveRuntimeSession(objective=body.objective)
    runtime_registry.add(session)
    sentry.set_tags(
        {
            "run_id": str(session.session_id),
            "session_id": str(session.session_id),
        }
    )

    for spec in body.workers:
        await session.register_worker(
            spec.id,
            spec.role,
            upstream=tuple(spec.upstream),
            replaces=spec.replaces,
            model_backed=spec.model_backed,
        )
    return _summary(session)


@router.delete("/sessions", response_model=RuntimeResetResponse)
async def reset_sessions() -> RuntimeResetResponse:
    """Reset Demo. Drops every live session; the simulator is untouched."""
    cleared = len(runtime_registry)
    runtime_registry.clear()
    return RuntimeResetResponse(cleared=cleared)


# Declared before /sessions/{session_id} so "current" is not parsed as a UUID.
@router.get("/sessions/current", response_model=RuntimeSessionSummary)
async def get_current_session() -> RuntimeSessionSummary:
    """The session the /demo screen attaches to when it holds no id."""
    session = runtime_registry.latest()
    if session is None:
        raise HTTPException(status_code=404, detail="no live runtime session")
    return _summary(session)


@router.get("/sessions/{session_id}", response_model=RuntimeSessionSummary)
async def get_session(session_id: UUID) -> RuntimeSessionSummary:
    return _summary(_require(session_id))


@router.get("/sessions/{session_id}/events", response_model=RuntimeEventPage)
async def get_session_events(session_id: UUID, since_seq: int = -1) -> RuntimeEventPage:
    session = _require(session_id)
    events = session.bus.since(since_seq)
    if events is None:
        raise HTTPException(
            status_code=409,
            detail="since_seq is older than the replay buffer; reconnect for a snapshot",
        )
    return RuntimeEventPage(
        session_id=session.session_id, last_seq=session.last_seq, events=events
    )


@router.get("/sessions/{session_id}/snapshot", response_model=SnapshotFrame)
async def get_session_snapshot(session_id: UUID) -> SnapshotFrame:
    """The same SnapshotFrame the WebSocket sends on connect.

    Exists so a client attaching to a run already in progress -- or opening
    /demo after it finished -- can rebuild the whole picture: this snapshot
    for the graph, then GET /events for the timeline, then the socket from
    `snapshot.last_seq` onward with no gap.
    """
    return _require(session_id).snapshot()


@router.post(
    "/sessions/{session_id}/workers",
    response_model=RuntimeSessionSummary,
    status_code=201,
)
async def register_worker(
    session_id: UUID, body: WorkerRegistrationRequest
) -> RuntimeSessionSummary:
    session = _require(session_id)
    spec = body.worker
    await session.register_worker(
        spec.id,
        spec.role,
        upstream=tuple(spec.upstream),
        replaces=spec.replaces,
        model_backed=spec.model_backed,
    )
    return _summary(session)


# --- THE decision ---------------------------------------------------------


@router.post("/sessions/{session_id}/resource-request", response_model=ResourceDecision)
async def request_resource(session_id: UUID, body: ResourceRequest) -> ResourceDecision:
    """Evaluate one resource request. Synchronous; the flow obeys the answer.

    Ordering that is load-bearing and easy to break by rearranging: the policy
    is evaluated and the full deny cascade is emitted *before* anything is
    read, and the read happens only on the allow branch.
    """
    session = _require(session_id)
    _worker_call(session, body.worker_id)

    with sentry.span(
        "agentshield.policy_check",
        f"policy check {body.worker_id}",
        run_id=str(session.session_id),
        worker_id=body.worker_id,
        role=session.workers[body.worker_id].role,
        event_type="policy_check",
        resource_path=body.resource_path,
    ):
        try:
            grant = await session.request_resource(body.worker_id, body.resource_path)
        except UnknownWorkerError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    decision = grant.decision
    response = ResourceDecision(
        decision=decision.decision,
        rule=decision.rule,
        reason=decision.reason,
        resource_path=body.resource_path,
        normalized_path=decision.normalized_path,
        quarantined=grant.quarantined,
        recovery_required=grant.recovery_required,
    )

    if not decision.allowed:
        _log_denial(session, body, decision, grant.quarantined)
        return response

    if body.include_content and decision.normalized_path is not None:
        try:
            response.content = read_sandbox_resource(decision.normalized_path)
        except ResourceAccessError as exc:
            response.error = str(exc)
        except PolicyBypassError:
            # Unreachable unless the two halves of the enforcement point have
            # been allowed to disagree. Fail closed and say so loudly.
            logger.exception("policy bypass guard tripped for %s", decision.normalized_path)
            raise HTTPException(status_code=500, detail="policy bypass guard tripped") from None

    return response


def _log_denial(
    session: LiveRuntimeSession,
    body: ResourceRequest,
    decision: object,
    quarantined: bool,
) -> None:
    rule = getattr(decision, "rule", "unknown")
    reason = getattr(decision, "reason", "")

    sentry.log_event(
        "security.tool_denied",
        f"Denied {body.worker_id} -> {body.resource_path}",
        session_id=str(session.session_id),
        run_id=str(session.session_id),
        worker_id=body.worker_id,
        # The requested path only. The resource was never opened, so there is
        # nothing else that could be logged even by accident.
        resource_path=body.resource_path,
        rule=rule,
        policy_result="deny",
        security_state="quarantined" if quarantined else "active",
    )
    if rule == "quarantined_worker":
        return

    sentry.log_event(
        "security.policy_violation",
        f"Policy violation by {body.worker_id}: {reason}",
        session_id=str(session.session_id),
        run_id=str(session.session_id),
        worker_id=body.worker_id,
        resource_path=body.resource_path,
        violation_type=rule,
        policy_result="deny",
    )
    if quarantined:
        worker = session.workers[body.worker_id]
        with sentry.span(
            "agentshield.quarantine",
            f"quarantine {body.worker_id}",
            run_id=str(session.session_id),
            worker_id=body.worker_id,
            role=worker.role,
            rule=rule,
            security_state="quarantined",
            violation_type=rule,
        ):
            sentry.log_event(
                "security.agent_quarantined",
                f"Quarantined {worker.role} ({body.worker_id})",
                session_id=str(session.session_id),
                run_id=str(session.session_id),
                worker_id=body.worker_id,
                role=worker.role,
                security_state="quarantined",
                rule=rule,
                violation_type=rule,
                tainted_artifact_ids=[
                    a.id for a in session.artifacts.values() if not a.trusted
                ],
            )


@router.post(
    "/sessions/{session_id}/model-call",
    response_model=RuntimeSessionSummary,
    status_code=202,
)
async def record_model_call(
    session_id: UUID, body: ModelCallRequest
) -> RuntimeSessionSummary:
    """Record that a worker's reasoning came from a real model call.

    Identity and timing only -- no prompt, no completion, no credential. The
    presence of these events is what distinguishes a model-backed run from one
    using deterministic stand-ins, so it must be recorded by the side that
    actually made the call rather than asserted anywhere else.
    """
    session = _require(session_id)
    _worker_call(session, body.worker_id)
    try:
        await session.record_model_call(
            body.worker_id,
            provider=body.provider,
            model=body.model,
            endpoint_host=body.endpoint_host,
            latency_ms=body.latency_ms,
            prompt_chars=body.prompt_chars,
            response_chars=body.response_chars,
            prompt_tokens=body.prompt_tokens,
            completion_tokens=body.completion_tokens,
        )
    except UnknownWorkerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _summary(session)


# --- workflow lifecycle ---------------------------------------------------


@router.post(
    "/sessions/{session_id}/tasks/start",
    response_model=RuntimeSessionSummary,
    status_code=202,
)
async def start_task(session_id: UUID, body: TaskStartRequest) -> RuntimeSessionSummary:
    session = _require(session_id)
    _worker_call(session, body.worker_id)
    try:
        await session.start_worker(body.worker_id, body.task)
    except UnknownWorkerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _summary(session)


@router.post(
    "/sessions/{session_id}/tasks/complete",
    response_model=RuntimeSessionSummary,
    status_code=202,
)
async def complete_task(session_id: UUID, body: TaskCompleteRequest) -> RuntimeSessionSummary:
    session = _require(session_id)
    _worker_call(session, body.worker_id)
    try:
        await session.complete_task(body.worker_id, step_name=body.step, detail=body.detail)
    except UnknownWorkerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if body.step == "patch":
        sentry.log_event(
            "developer.patch_applied",
            f"Patch applied by {body.worker_id}",
            session_id=str(session.session_id),
            run_id=str(session.session_id),
            worker_id=body.worker_id,
            phase="fix",
        )
    return _summary(session)


@router.post(
    "/sessions/{session_id}/artifacts",
    response_model=RuntimeSessionSummary,
    status_code=201,
)
async def record_artifact(session_id: UUID, body: ArtifactRequest) -> RuntimeSessionSummary:
    session = _require(session_id)
    _worker_call(session, body.worker_id)
    session.record_artifact(body.id, body.worker_id, body.kind, body.summary)
    return _summary(session)


@router.post(
    "/sessions/{session_id}/reassign",
    response_model=RuntimeSessionSummary,
    status_code=202,
)
async def reassign(session_id: UUID, body: ReassignRequest) -> RuntimeSessionSummary:
    """Hand a quarantined worker's task to a genuinely new replacement.

    The replacement's seed context is validated here: naming a tainted
    artifact is a 409, not a warning. That check is the difference between
    containment and theatre.
    """
    session = _require(session_id)
    _worker_call(session, body.from_worker_id)

    try:
        session.assert_context_is_trusted(body.context_artifact_ids)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    with sentry.span(
        "swarm.task_reassigned",
        f"reassign {body.from_worker_id} -> {body.to_worker.id}",
        run_id=str(session.session_id),
        from_worker_id=body.from_worker_id,
        to_worker_id=body.to_worker.id,
        role=body.to_worker.role,
        replaces=body.from_worker_id,
        replacement_worker_id=body.to_worker.id,
    ):
        await session.reassign(
            from_worker_id=body.from_worker_id,
            to_worker_id=body.to_worker.id,
            role=body.to_worker.role,
            task=body.task,
            upstream=tuple(body.to_worker.upstream),
            model_backed=body.to_worker.model_backed,
        )

    sentry.log_event(
        "swarm.task_reassigned",
        f"Task reassigned from {body.from_worker_id} to {body.to_worker.id}",
        session_id=str(session.session_id),
        run_id=str(session.session_id),
        from_worker_id=body.from_worker_id,
        to_worker_id=body.to_worker.id,
        replacement_relationship={
            "from_worker_id": body.from_worker_id,
            "to_worker_id": body.to_worker.id,
        },
    )
    sentry.log_event(
        "swarm.replacement_started",
        f"{body.to_worker.role} started with trusted context only",
        session_id=str(session.session_id),
        run_id=str(session.session_id),
        worker_id=body.to_worker.id,
        role=body.to_worker.role,
        replaces=body.from_worker_id,
        replacement_worker_id=body.to_worker.id,
        security_state="active",
        context_artifact_ids=body.context_artifact_ids,
    )
    return _summary(session)


@router.post(
    "/sessions/{session_id}/test-run",
    response_model=RuntimeSessionSummary,
    status_code=202,
)
async def record_test_run(session_id: UUID, body: TestRunRequest) -> RuntimeSessionSummary:
    """Record a real test run. A red run is recorded red -- that honesty is
    the reason a real run is in the demo instead of a claim."""
    session = _require(session_id)
    _worker_call(session, body.worker_id)
    try:
        await session.record_test_run(
            body.worker_id,
            passed=body.passed,
            summary=body.summary,
            exit_code=body.exit_code,
            command=body.command,
        )
    except UnknownWorkerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if body.passed:
        sentry.log_event(
            "swarm.tests_passed",
            f"{body.command}: {body.summary}",
            session_id=str(session.session_id),
            run_id=str(session.session_id),
            worker_id=body.worker_id,
            exit_code=body.exit_code,
            pytest_exit_code=body.exit_code,
            phase="after_fix",
            tests_passed=True,
        )
    else:
        sentry.log_event(
            "developer.regression_failed",
            "Regression suite failed",
            session_id=str(session.session_id),
            run_id=str(session.session_id),
            worker_id=body.worker_id,
            exit_code=body.exit_code,
            pytest_exit_code=body.exit_code,
            phase="test_run",
        )
    return _summary(session)


@router.post(
    "/sessions/{session_id}/recover",
    response_model=RuntimeSessionSummary,
    status_code=202,
)
async def recover(session_id: UUID, body: RecoverRequest) -> RuntimeSessionSummary:
    session = _require(session_id)
    await session.recover(summary=body.summary)
    sentry.log_event(
        "swarm.recovery_complete",
        "Swarm recovery completed",
        session_id=str(session.session_id),
        run_id=str(session.session_id),
        attack_detected=session.attack_detected,
        tests_passed=session.tests_passed,
        phase="recovery",
    )
    return _summary(session)


@router.post(
    "/sessions/{session_id}/fail",
    response_model=RuntimeSessionSummary,
    status_code=202,
)
async def fail(session_id: UUID, body: FailRequest) -> RuntimeSessionSummary:
    session = _require(session_id)
    await session.fail(reason=body.reason)
    return _summary(session)


# --- post-hoc commentary --------------------------------------------------


@router.get("/sessions/{session_id}/explanation", response_model=IncidentExplanation)
async def get_explanation(session_id: UUID, request: Request) -> IncidentExplanation:
    """Runs strictly after the deterministic decision is recorded, and never
    feeds back into it (docs/ARCHITECTURE.md §4)."""
    session = _require(session_id)
    return await explain_incident(session, get_settings(), request.app.state.http_client)


# --- the stream -----------------------------------------------------------


@router.websocket("/sessions/{session_id}/stream")
async def runtime_stream(
    websocket: WebSocket, session_id: UUID, since_seq: int | None = None
) -> None:
    """Structurally a copy of app/api/ws.py, not a generalization of it.

    The subscribe-before-snapshot ordering below is load-bearing and easy to
    break by rearranging: subscribe first, so a concurrent publish cannot slip
    through the gap between subscribing and reading the snapshot.
    """
    session = runtime_registry.get(session_id)
    if session is None:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    queue = session.bus.subscribe()
    try:
        backlog = session.bus.since(since_seq) if since_seq is not None else None

        if backlog is None:
            snapshot = session.snapshot()
            await websocket.send_text(snapshot.model_dump_json())
            last_sent_seq = snapshot.last_seq
        else:
            last_sent_seq = since_seq
            for event in backlog:
                await websocket.send_text(EventFrame(event=event).model_dump_json())
                last_sent_seq = event.seq

        while True:
            event = await queue.get()
            if event.seq <= last_sent_seq:
                continue
            await websocket.send_text(EventFrame(event=event).model_dump_json())
            last_sent_seq = event.seq
    except WebSocketDisconnect:
        pass
    finally:
        session.bus.unsubscribe(queue)
