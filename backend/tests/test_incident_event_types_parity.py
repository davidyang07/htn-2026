"""There is no compiler/codegen coverage for enum *values* across languages
(openapi-typescript keeps shapes honest, not literal string sets) -- this
pins the backend's INCIDENT_EVENT_TYPES to the exact literal set expected to
match frontend/src/lib/stream/reducer.ts's INCIDENT_EVENT_TYPES, so a
one-sided edit to either side fails loudly instead of silently diverging."""

from app.schemas.events import INCIDENT_EVENT_TYPES

# Mirrors frontend/src/lib/stream/reducer.ts:16-22 verbatim.
EXPECTED_FRONTEND_INCIDENT_EVENT_TYPES = {
    "COMPROMISE_ATTEMPTED",
    "COMPROMISE_SUCCEEDED",
    "COMPROMISE_FAILED",
    "ANOMALY_DETECTED",
    "AGENT_QUARANTINED",
}


def test_incident_event_types_match_frontend_literal_set():
    backend_values = {t.value for t in INCIDENT_EVENT_TYPES}
    assert backend_values == EXPECTED_FRONTEND_INCIDENT_EVENT_TYPES
