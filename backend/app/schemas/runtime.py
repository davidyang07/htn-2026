"""Request/response models for the live runtime API (docs/MVP_PLAN.md P0.4).

Every one of these crosses the process boundary between the WorkSwarm
SwarmFlow and AgentShield, so each new or changed model here costs an OpenAPI
regeneration (`make types`) and a committed `frontend/src/lib/api/schema.d.ts`.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.engine.state import SecurityState
from app.schemas.events import Event

WorkflowState = Literal["idle", "running", "under_attack", "recovering", "recovered", "failed"]


class WorkerSpec(BaseModel):
    """One worker the flow is about to run."""

    id: str = Field(..., min_length=1, max_length=64)
    role: str = Field(..., min_length=1, max_length=64)
    #: Worker ids this one receives work from. Draws the collaboration graph.
    upstream: list[str] = Field(default_factory=list)
    #: Set on a replacement worker only.
    replaces: str | None = None
    #: Whether a real model call backs this worker's decisions. Recorded
    #: honestly so the UI never implies an LLM ran when none was configured.
    model_backed: bool = False


class SessionCreateRequest(BaseModel):
    objective: str = Field(..., min_length=1, max_length=1000)
    workers: list[WorkerSpec] = Field(default_factory=list)
    #: Replace any existing session. The demo's Reset button and the flow's
    #: start-up both want exactly one live session at a time.
    reset: bool = True


class WorkerRegistrationRequest(BaseModel):
    worker: WorkerSpec


class ResourceRequest(BaseModel):
    """THE decision request. Nothing is read before it is answered."""

    worker_id: str = Field(..., min_length=1, max_length=64)
    resource_path: str = Field(..., max_length=2000)
    #: When true, an *allowed* response also carries the resource's text, so
    #: the flow does not need filesystem access of its own. A denied response
    #: never carries content, because nothing was read.
    include_content: bool = True


class ResourceDecision(BaseModel):
    decision: Literal["allow", "deny"]
    rule: str
    reason: str
    resource_path: str
    normalized_path: str | None = None
    quarantined: bool = False
    recovery_required: bool = False
    #: Present only on an allow, and only when `include_content` was set.
    content: str | None = None
    #: Set when an allowed path could not be read (missing file, too large).
    #: Distinct from a denial: the policy said yes, the filesystem said no.
    error: str | None = None


class TaskStartRequest(BaseModel):
    worker_id: str
    task: str = Field(..., min_length=1, max_length=1000)


class TaskCompleteRequest(BaseModel):
    worker_id: str
    step: str = Field(..., min_length=1, max_length=64)
    detail: str = Field("", max_length=4000)


class ArtifactRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    worker_id: str
    kind: str = Field(..., min_length=1, max_length=32)
    summary: str = Field("", max_length=4000)


class ReassignRequest(BaseModel):
    from_worker_id: str
    to_worker: WorkerSpec
    task: str = Field(..., min_length=1, max_length=1000)
    #: Artifact ids the replacement will be seeded with. Rejected with 409 if
    #: any of them is tainted -- the replacement's whole value is that the
    #: poisoned context did not reach it.
    context_artifact_ids: list[str] = Field(default_factory=list)


class ModelCallRequest(BaseModel):
    """Evidence that a worker's reasoning came from a real model call.

    Carries what identifies the call and how long it took -- never a prompt, a
    completion, or a credential. It exists so "this worker was model-backed"
    is a recorded fact on the event stream rather than a claim in a README.
    """

    worker_id: str
    provider: str = Field(..., max_length=64)
    model: str = Field(..., max_length=128)
    #: Host only, never the full URL with any query or credential.
    endpoint_host: str = Field("", max_length=128)
    #: Truthful execution route. In particular, ``sponsor_fallback`` means a
    #: configured/verified RunPod route did not answer this invocation.
    provider_route: Literal["runpod", "sponsor", "sponsor_fallback"] = "sponsor"
    fallback_used: bool = False
    #: Sanitized cause only; never an exception message, URL, or credential.
    fallback_reason: str = Field("", max_length=200)
    latency_ms: int = Field(..., ge=0)
    #: Sizes, not contents.
    prompt_chars: int = Field(0, ge=0)
    response_chars: int = Field(0, ge=0)
    #: Present only when the provider surfaces it; `LLMComponent` does not
    #: return usage metadata, so this is usually absent.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class TestRunRequest(BaseModel):
    worker_id: str
    command: str = Field(..., max_length=500)
    exit_code: int
    passed: bool
    summary: str = Field(..., max_length=1000)


class RecoverRequest(BaseModel):
    summary: str = Field(..., min_length=1, max_length=2000)


class FailRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class WorkerView(BaseModel):
    id: str
    role: str
    security_state: SecurityState
    current_task: str | None = None
    #: Worker ids this one receives work from. Carried here as well as in the
    #: stream's EdgeView so the /demo graph can be drawn from the summary
    #: alone -- a client attached before a replacement worker was created
    #: never sees it otherwise, because the shared stream reducer creates
    #: nodes from snapshots, not from AGENT_CREATED.
    upstream: list[str] = Field(default_factory=list)
    replaces: str | None = None
    model_backed: bool = False
    quarantine_reason: str | None = None
    step_quarantined: int | None = None


class ArtifactView(BaseModel):
    id: str
    worker_id: str
    kind: str
    summary: str
    trusted: bool
    taint_reason: str | None = None


class RuntimeSessionSummary(BaseModel):
    session_id: UUID
    objective: str
    workflow_state: WorkflowState
    step: int
    last_seq: int
    attack_detected: bool
    recovery_required: bool
    #: Real model calls recorded this run. Zero means every worker ran as a
    #: deterministic stand-in -- surfaced so the UI never has to guess.
    model_calls: int = 0
    tests_passed: bool | None = None
    test_summary: str | None = None
    workers: list[WorkerView]
    artifacts: list[ArtifactView]


class RuntimeEventPage(BaseModel):
    session_id: UUID
    last_seq: int
    events: list[Event]


class RuntimeResetResponse(BaseModel):
    cleared: int

