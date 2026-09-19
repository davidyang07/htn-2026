from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue

from app.events.version import SCHEMA_VERSION


class EventType(StrEnum):
    EXPERIMENT_STARTED = "EXPERIMENT_STARTED"
    EXPERIMENT_STOPPED = "EXPERIMENT_STOPPED"
    AGENT_CREATED = "AGENT_CREATED"
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_STOPPED = "AGENT_STOPPED"
    MESSAGE_SENT = "MESSAGE_SENT"
    MESSAGE_RECEIVED = "MESSAGE_RECEIVED"
    MODEL_REQUESTED = "MODEL_REQUESTED"
    MODEL_RESPONDED = "MODEL_RESPONDED"
    TOOL_REQUESTED = "TOOL_REQUESTED"
    TOOL_EXECUTED = "TOOL_EXECUTED"
    TOOL_DENIED = "TOOL_DENIED"
    MEMORY_READ = "MEMORY_READ"
    MEMORY_WRITE = "MEMORY_WRITE"
    CREDENTIAL_ACCESSED = "CREDENTIAL_ACCESSED"
    CREDENTIAL_REVOKED = "CREDENTIAL_REVOKED"
    COMPROMISE_ATTEMPTED = "COMPROMISE_ATTEMPTED"
    COMPROMISE_SUCCEEDED = "COMPROMISE_SUCCEEDED"
    COMPROMISE_FAILED = "COMPROMISE_FAILED"
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
    AGENT_QUARANTINED = "AGENT_QUARANTINED"
    AGENT_RELEASED = "AGENT_RELEASED"
    PERMISSION_CHANGED = "PERMISSION_CHANGED"
    INFERENCE_DISABLED = "INFERENCE_DISABLED"
    THREAT_SIGNATURE_PUBLISHED = "THREAT_SIGNATURE_PUBLISHED"
    THREAT_SIGNATURE_RECEIVED = "THREAT_SIGNATURE_RECEIVED"
    AGENT_RECOVERED = "AGENT_RECOVERED"
    # Byzantine/security-plane attacks (docs/PLAN.md §5): the generic
    # compromise substrate for scenarios where the violation itself -- not a
    # probabilistic draw -- is the meaningful unit (metadata.violation_type
    # discriminates, e.g. "sentinel_subverted", "credential_scope_exceeded").
    POLICY_VIOLATION = "POLICY_VIOLATION"
    # Attestation replay (docs/PLAN.md §5): ATTESTATION_VERIFIED carries
    # metadata.replayed=true when a stale nonce is presented -- mechanical,
    # deterministic, no LLM judge needed.
    ATTESTATION_ISSUED = "ATTESTATION_ISSUED"
    ATTESTATION_VERIFIED = "ATTESTATION_VERIFIED"


# M0 emits only this subset (SPEC §3.5).
M0_EVENT_TYPES = frozenset(
    {
        EventType.EXPERIMENT_STARTED,
        EventType.EXPERIMENT_STOPPED,
        EventType.AGENT_CREATED,
        EventType.COMPROMISE_ATTEMPTED,
        EventType.COMPROMISE_SUCCEEDED,
        EventType.COMPROMISE_FAILED,
    }
)

# M1 additionally emits detection/quarantine events (M1_PLAN §4).
M1_EVENT_TYPES = M0_EVENT_TYPES | frozenset(
    {
        EventType.ANOMALY_DETECTED,
        EventType.AGENT_QUARANTINED,
    }
)

# Phase 2 additionally emits model/tool interaction events for real
# (LLM-backed) agents' lateral prompt-injection attempts
# (docs/PHASE_2_PLAN.md §7). COMPROMISE_*/ANOMALY_DETECTED/AGENT_QUARANTINED
# are reused verbatim -- these three are the only genuinely new emitted types.
PHASE_2_EVENT_TYPES = M1_EVENT_TYPES | frozenset(
    {
        EventType.MODEL_REQUESTED,
        EventType.MODEL_RESPONDED,
        EventType.TOOL_EXECUTED,
    }
)

# Event types with per-agent security significance for the incident timeline
# -- mirrors frontend/src/lib/stream/reducer.ts's INCIDENT_EVENT_TYPES
# exactly. There is no codegen coverage for enum *values* across languages
# (only shapes), so backend/tests/test_incident_event_types_parity.py and a
# frontend counterpart assert these two literal sets never drift apart.
INCIDENT_EVENT_TYPES = frozenset(
    {
        EventType.COMPROMISE_ATTEMPTED,
        EventType.COMPROMISE_SUCCEEDED,
        EventType.COMPROMISE_FAILED,
        EventType.ANOMALY_DETECTED,
        EventType.AGENT_QUARANTINED,
    }
)


class EventDraft(BaseModel):
    """Engine output: no identity, no clock. This is what keeps step() pure."""

    sim_tick: int
    event_type: EventType
    agent_id: str | None = None
    source_agent_id: str | None = None
    target_agent_id: str | None = None
    risk_score: float | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class Event(EventDraft):
    """Emitted, ordered, streamable."""

    event_id: UUID
    seq: int
    schema_version: int = SCHEMA_VERSION
    experiment_id: UUID
    wall_time: datetime
