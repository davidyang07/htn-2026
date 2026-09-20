import { describe, expect, it } from "vitest";

import type { Event } from "@/lib/stream/reducer";

import { deriveNarrative } from "./narrative";

const SESSION = "88888888-8888-8888-8888-888888888888";

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

function labels(events: Event[]): string[] {
  return deriveNarrative(events).map((beat) => beat.label);
}

describe("deriveNarrative", () => {
  it("registers the team as one beat, not one beat per worker", () => {
    nextSeq = 0;
    const beats = deriveNarrative([
      event("AGENT_CREATED", { agent_id: "repo-analyst", metadata: { role: "Repo Analyst" } }),
      event("AGENT_CREATED", { agent_id: "developer", metadata: { role: "Developer" } }),
      event("AGENT_CREATED", { agent_id: "reviewer", metadata: { role: "Reviewer" } }),
    ]);
    expect(beats).toHaveLength(1);
    expect(beats[0]!.label).toBe("Team assembled");
    expect(beats[0]!.detail).toBe("3 workers registered");
  });

  it("has nothing to tell about an empty stream", () => {
    expect(deriveNarrative([])).toEqual([]);
  });

  it("folds a worker's reads and calls into one activity beat", () => {
    nextSeq = 0;
    const beats = deriveNarrative([
      event("AGENT_CREATED", {
        agent_id: "security-researcher",
        metadata: { role: "Security Researcher" },
      }),
      event("TOOL_REQUESTED", { agent_id: "security-researcher" }),
      event("TOOL_EXECUTED", { agent_id: "security-researcher" }),
      event("TOOL_REQUESTED", { agent_id: "security-researcher" }),
      event("TOOL_EXECUTED", { agent_id: "security-researcher" }),
      event("MODEL_REQUESTED", { agent_id: "security-researcher" }),
      event("MODEL_RESPONDED", { agent_id: "security-researcher" }),
    ]);
    expect(beats.map((b) => b.label)).toEqual([
      "Team assembled",
      "Security Researcher working",
    ]);
    expect(beats[1]).toMatchObject({ kind: "activity", count: 5 });
    expect(beats[1]!.detail).toBe("2 files requested, 2 files read, 1 model call");
  });

  it("never double-counts a model call from its response event", () => {
    nextSeq = 0;
    const beats = deriveNarrative([
      event("MODEL_REQUESTED", { agent_id: "developer" }),
      event("MODEL_RESPONDED", { agent_id: "developer" }),
      event("MODEL_REQUESTED", { agent_id: "developer" }),
      event("MODEL_RESPONDED", { agent_id: "developer" }),
    ]);
    expect(beats[0]!.detail).toBe("2 model calls");
  });

  it("does not fold two different workers into one beat", () => {
    nextSeq = 0;
    const beats = deriveNarrative([
      event("TOOL_EXECUTED", { agent_id: "repo-analyst" }),
      event("TOOL_EXECUTED", { agent_id: "developer" }),
    ]);
    expect(beats).toHaveLength(2);
  });

  it("gives every incident beat a row of its own, in order", () => {
    nextSeq = 0;
    expect(
      labels([
        event("AGENT_CREATED", {
          agent_id: "security-researcher",
          metadata: { role: "Security Researcher" },
        }),
        event("TASK_ASSIGNED", { agent_id: "security-researcher" }),
        event("TOOL_REQUESTED", { agent_id: "security-researcher" }),
        event("TOOL_DENIED", {
          agent_id: "security-researcher",
          metadata: { resource: "demo_target/secrets/demo_secret.txt" },
        }),
        event("POLICY_VIOLATION", { agent_id: "security-researcher" }),
        event("ANOMALY_DETECTED", { agent_id: "security-researcher" }),
        event("AGENT_QUARANTINED", { agent_id: "security-researcher" }),
        event("TASK_REASSIGNED", { target_agent_id: "replacement-researcher" }),
      ]),
    ).toEqual([
      "Team assembled",
      "Task assigned",
      "Security Researcher working",
      "AgentShield denied the request",
      "Policy violation",
      "Anomaly detected",
      "Worker quarantined",
      "Task reassigned",
    ]);
  });

  it("reads a red test run red and a green one green", () => {
    nextSeq = 0;
    const beats = deriveNarrative([
      event("TASK_COMPLETED", {
        agent_id: "developer",
        metadata: { step: "pytest", passed: false, detail: "4 failed, 10 passed in 0.29s" },
      }),
      event("TASK_COMPLETED", {
        agent_id: "developer",
        metadata: { step: "pytest", passed: true, detail: "14 passed in 0.13s" },
      }),
    ]);
    expect(beats.map((b) => [b.label, b.severity, b.detail])).toEqual([
      ["Regression suite failed", "critical", "4 failed, 10 passed in 0.29s"],
      ["Regression suite passed", "ok", "14 passed in 0.13s"],
    ]);
  });

  it("marks only the replacement's start as a milestone", () => {
    nextSeq = 0;
    const beats = deriveNarrative([
      event("AGENT_CREATED", { agent_id: "developer", metadata: { role: "Developer" } }),
      event("AGENT_STARTED", { agent_id: "developer" }),
      event("AGENT_CREATED", {
        agent_id: "replacement-researcher",
        metadata: { role: "Replacement Researcher", replaces: "security-researcher" },
      }),
      event("AGENT_STARTED", {
        agent_id: "replacement-researcher",
        metadata: { context_policy: "trusted_artifacts_only" },
      }),
    ]);
    expect(beats.map((b) => b.label)).toEqual([
      "Team assembled",
      "Developer working",
      "Replacement worker created",
      "Replacement started on trusted context only",
    ]);
  });

  it("names a worker by its registered role", () => {
    nextSeq = 0;
    const beats = deriveNarrative([
      event("AGENT_CREATED", { agent_id: "developer", metadata: { role: "Developer" } }),
      event("TASK_ASSIGNED", { agent_id: "developer", metadata: { task: "Patch it." } }),
    ]);
    const assigned = beats.find((b) => b.label === "Task assigned");
    expect(assigned?.actorRole).toBe("Developer");
    expect(assigned?.detail).toBe("Patch it.");
  });

  it("falls back to the raw step name rather than dropping the beat", () => {
    nextSeq = 0;
    expect(
      labels([
        event("TASK_COMPLETED", { agent_id: "developer", metadata: { step: "unheard_of" } }),
      ]),
    ).toEqual(["unheard_of"]);
  });

  it("keeps every event accounted for", () => {
    nextSeq = 0;
    const events = [
      event("AGENT_CREATED", { agent_id: "developer", metadata: { role: "Developer" } }),
      event("TOOL_REQUESTED", { agent_id: "developer" }),
      event("TOOL_EXECUTED", { agent_id: "developer" }),
      event("TASK_COMPLETED", { agent_id: "developer", metadata: { step: "patch" } }),
      event("WORKFLOW_RECOVERED", {}),
    ];
    const folded = deriveNarrative(events).reduce((sum, beat) => sum + beat.count, 0);
    expect(folded).toBe(events.length);
  });
});
