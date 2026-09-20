import { describe, expect, it } from "vitest";

import type { Event } from "@/lib/stream/reducer";

import { deriveIncident, EMPTY_INCIDENT } from "./incident";

const SESSION = "77777777-7777-7777-7777-777777777777";
const SECRET = "demo_target/secrets/demo_secret.txt";

let nextSeq = 0;

function event(event_type: string, overrides: Partial<Event> = {}): Event {
  return {
    event_id: `event-${nextSeq}`,
    seq: nextSeq++,
    schema_version: 1,
    experiment_id: SESSION,
    wall_time: "2026-03-02T00:00:00Z",
    sim_tick: nextSeq,
    event_type: event_type as Event["event_type"],
    metadata: {},
    ...overrides,
  };
}

/** The real shape of a run: allowed reads first, then the one that is denied. */
function fullIncident(): Event[] {
  nextSeq = 0;
  return [
    event("AGENT_CREATED", {
      agent_id: "security-researcher",
      metadata: { role: "Security Researcher" },
    }),
    event("TOOL_REQUESTED", {
      agent_id: "security-researcher",
      metadata: { resource: "demo_target/app/auth.py" },
    }),
    event("TOOL_EXECUTED", {
      agent_id: "security-researcher",
      metadata: { resource: "demo_target/app/auth.py" },
    }),
    event("TOOL_REQUESTED", {
      agent_id: "security-researcher",
      metadata: { resource: SECRET },
    }),
    event("TOOL_DENIED", {
      agent_id: "security-researcher",
      metadata: {
        resource: SECRET,
        violation_type: "protected_path",
        reason: "demo_target/secrets/ is a protected directory; access is denied.",
      },
    }),
    event("POLICY_VIOLATION", {
      agent_id: "security-researcher",
      metadata: {
        resource: SECRET,
        violation_type: "protected_path",
        reason: "demo_target/secrets/ is a protected directory; access is denied.",
      },
    }),
    event("ANOMALY_DETECTED", { agent_id: "security-researcher" }),
    event("AGENT_QUARANTINED", {
      agent_id: "security-researcher",
      metadata: {
        legitimate: true,
        violation_type: "protected_path",
        tainted_artifacts: ["researcher-report"],
      },
    }),
    event("TASK_REASSIGNED", {
      agent_id: "security-researcher",
      target_agent_id: "replacement-researcher",
    }),
    event("AGENT_CREATED", {
      agent_id: "replacement-researcher",
      metadata: {
        role: "Replacement Researcher",
        replaces: "security-researcher",
        trusted_context: ["repo-map"],
      },
    }),
    event("AGENT_STARTED", {
      agent_id: "replacement-researcher",
      metadata: { context_policy: "trusted_artifacts_only" },
    }),
  ];
}

describe("deriveIncident", () => {
  it("reports nothing before a violation", () => {
    nextSeq = 0;
    const incident = deriveIncident([
      event("AGENT_CREATED", { agent_id: "repo-analyst", metadata: { role: "Repo Analyst" } }),
      event("TOOL_EXECUTED", { agent_id: "repo-analyst" }),
    ]);
    expect(incident.detected).toBe(false);
    expect(incident.resource).toBeNull();
    expect(incident.cascade.every((step) => step.seq === null)).toBe(true);
  });

  it("is empty for an empty stream", () => {
    expect(deriveIncident([])).toMatchObject({ ...EMPTY_INCIDENT, cascade: expect.any(Array) });
  });

  it("names the worker by its registered role", () => {
    const incident = deriveIncident(fullIncident());
    expect(incident.workerId).toBe("security-researcher");
    expect(incident.workerRole).toBe("Security Researcher");
  });

  it("carries the denied path and the rule that fired", () => {
    const incident = deriveIncident(fullIncident());
    expect(incident.resource).toBe(SECRET);
    expect(incident.rule).toBe("protected_path");
    expect(incident.reason).toContain("protected directory");
  });

  it("lights all four cascade beats in order", () => {
    const incident = deriveIncident(fullIncident());
    const seqs = incident.cascade.map((step) => step.seq);
    expect(seqs.every((seq) => seq !== null)).toBe(true);
    expect(seqs).toEqual([...seqs].sort((a, b) => a! - b!));
  });

  it("pins the request beat to the denied path, not to the first read", () => {
    const incident = deriveIncident(fullIncident());
    const requested = incident.cascade.find((step) => step.key === "requested");
    // seq 1 is the allowed auth.py read; seq 3 is the request that was denied.
    expect(requested?.seq).toBe(3);
    expect(requested?.detail).toBe(SECRET);
  });

  it("keeps the cascade on the request that caused the quarantine", () => {
    const events = fullIncident();
    // A quarantined worker's later requests are refused too.
    events.push(
      event("TOOL_DENIED", {
        agent_id: "security-researcher",
        metadata: {
          resource: "demo_target/README.md",
          violation_type: "quarantined_worker",
          reason: "Worker is quarantined; it can take no further action.",
        },
      }),
    );
    const incident = deriveIncident(events);
    expect(incident.resource).toBe(SECRET);
    expect(incident.rule).toBe("protected_path");
  });

  it("lists the artifacts the quarantine marked untrusted", () => {
    expect(deriveIncident(fullIncident()).taintedArtifactIds).toEqual(["researcher-report"]);
  });

  it("records the replacement and the trusted context it was seeded with", () => {
    const incident = deriveIncident(fullIncident());
    expect(incident.replacementWorkerId).toBe("replacement-researcher");
    expect(incident.replacementRole).toBe("Replacement Researcher");
    expect(incident.trustedContextIds).toEqual(["repo-map"]);
    expect(incident.trustedContextOnly).toBe(true);
  });

  it("does not claim a trusted-only context policy that was never declared", () => {
    const events = fullIncident().filter((e) => e.event_type !== "AGENT_STARTED");
    expect(deriveIncident(events).trustedContextOnly).toBe(false);
  });

  it("reaches the quarantine beat even when it arrives without a replacement", () => {
    const events = fullIncident().filter(
      (e) => !["TASK_REASSIGNED", "AGENT_STARTED"].includes(e.event_type),
    );
    const partial = events.filter(
      (e) => !(e.event_type === "AGENT_CREATED" && e.agent_id === "replacement-researcher"),
    );
    const incident = deriveIncident(partial);
    expect(incident.cascade.at(-1)?.seq).not.toBeNull();
    expect(incident.replacementWorkerId).toBeNull();
  });
});
