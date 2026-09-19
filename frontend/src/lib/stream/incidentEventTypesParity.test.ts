import { describe, expect, it } from "vitest";

import { INCIDENT_EVENT_TYPES } from "./reducer";

// Mirrors backend/app/schemas/events.py's INCIDENT_EVENT_TYPES verbatim.
// There is no compiler/codegen coverage for enum *values* across languages
// (openapi-typescript keeps shapes honest, not literal string sets) -- this
// and backend/tests/test_incident_event_types_parity.py each pin their own
// side to the same expected literal set, so a one-sided edit to either
// fails loudly instead of silently diverging.
const EXPECTED_BACKEND_INCIDENT_EVENT_TYPES = new Set([
  "COMPROMISE_ATTEMPTED",
  "COMPROMISE_SUCCEEDED",
  "COMPROMISE_FAILED",
  "ANOMALY_DETECTED",
  "AGENT_QUARANTINED",
]);

describe("INCIDENT_EVENT_TYPES", () => {
  it("matches the backend literal set", () => {
    expect(INCIDENT_EVENT_TYPES).toEqual(EXPECTED_BACKEND_INCIDENT_EVENT_TYPES);
  });
});
