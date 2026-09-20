import { describe, expect, it } from "vitest";

import type { Event } from "@/lib/stream/reducer";

import { deriveVerdict, EMPTY_VERDICT, verdictLights } from "./verdict";

const SESSION = "33333333-3333-3333-3333-333333333333";

let nextSeq = 0;

function event(
  event_type: string,
  overrides: Partial<Event> = {},
): Event {
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

function fullRun(): Event[] {
  nextSeq = 0;
  return [
    event("AGENT_CREATED", { agent_id: "security-researcher" }),
    event("TOOL_REQUESTED", {
      agent_id: "security-researcher",
      metadata: { resource: "demo_target/secrets/demo_secret.txt" },
    }),
    event("TOOL_DENIED", { agent_id: "security-researcher" }),
    event("POLICY_VIOLATION", {
      agent_id: "security-researcher",
      metadata: {
        resource: "demo_target/secrets/demo_secret.txt",
        reason: "demo_target/secrets/ is a protected directory; access is denied.",
        violation_type: "protected_path",
      },
    }),
    event("ANOMALY_DETECTED", { agent_id: "security-researcher" }),
    event("AGENT_QUARANTINED", { agent_id: "security-researcher" }),
    event("TASK_REASSIGNED", { agent_id: "security-researcher" }),
    event("AGENT_CREATED", {
      agent_id: "replacement-researcher",
      metadata: { replaces: "security-researcher" },
    }),
    event("TASK_COMPLETED", {
      agent_id: "developer",
      metadata: { step: "patch", detail: "Enforced token expiry in verify_token()." },
    }),
    event("TASK_COMPLETED", {
      agent_id: "developer",
      metadata: {
        step: "pytest",
        detail: "8 passed in 0.08s",
        passed: true,
        command: "pytest demo_target",
      },
    }),
    event("TASK_COMPLETED", { agent_id: "reviewer", metadata: { step: "review", detail: "OK" } }),
    event("WORKFLOW_RECOVERED", { metadata: { summary: "Patched, tested and reviewed." } }),
  ];
}

describe("deriveVerdict", () => {
  it("is empty before anything has happened", () => {
    expect(deriveVerdict([])).toEqual(EMPTY_VERDICT);
  });

  it("lights every verdict from a full run", () => {
    const verdict = deriveVerdict(fullRun());
    expect(verdict.attackDetected).toBe(true);
    expect(verdict.agentQuarantined).toBe(true);
    expect(verdict.workflowRecovered).toBe(true);
    expect(verdict.testsPassed).toBe(true);
    expect(verdict.testSummary).toBe("8 passed in 0.08s");
    expect(verdict.testCommand).toBe("pytest demo_target");
    expect(verdict.quarantinedWorkerId).toBe("security-researcher");
    expect(verdict.replacementWorkerId).toBe("replacement-researcher");
    expect(verdict.deniedResource).toBe("demo_target/secrets/demo_secret.txt");
    expect(verdict.violationType).toBe("protected_path");
    expect(verdict.recoverySummary).toBe("Patched, tested and reviewed.");
  });

  it("records the three workflow steps in order", () => {
    const verdict = deriveVerdict(fullRun());
    expect(verdict.completedSteps.map((s) => s.step)).toEqual(["patch", "pytest", "review"]);
  });

  it("never lights a verdict without the event that earns it", () => {
    const upToQuarantine = fullRun().slice(0, 6);
    const verdict = deriveVerdict(upToQuarantine);
    expect(verdict.attackDetected).toBe(true);
    expect(verdict.agentQuarantined).toBe(true);
    expect(verdict.workflowRecovered).toBe(false);
    expect(verdict.testsPassed).toBeNull();
  });

  it("reads a red test run as red, not as pending", () => {
    nextSeq = 0;
    const verdict = deriveVerdict([
      event("TASK_COMPLETED", {
        agent_id: "developer",
        metadata: {
          step: "pytest",
          detail: "1 failed, 7 passed in 0.21s",
          passed: false,
          command: "pytest demo_target",
        },
      }),
    ]);
    expect(verdict.testsPassed).toBe(false);
    expect(verdict.testSummary).toBe("1 failed, 7 passed in 0.21s");
  });

  it("does not treat a missing `passed` flag as a pass", () => {
    nextSeq = 0;
    const verdict = deriveVerdict([
      event("TASK_COMPLETED", { metadata: { step: "pytest", detail: "who knows" } }),
    ]);
    expect(verdict.testsPassed).toBe(false);
  });

  it("does not mistake an ordinary AGENT_CREATED for a replacement", () => {
    nextSeq = 0;
    const verdict = deriveVerdict([event("AGENT_CREATED", { agent_id: "developer" })]);
    expect(verdict.replacementWorkerId).toBeNull();
  });
});

describe("verdictLights", () => {
  it("is all pending before the run starts", () => {
    const lights = verdictLights(EMPTY_VERDICT);
    expect(lights.map((l) => l.status)).toEqual(["pending", "pending", "pending", "pending"]);
    expect(lights.map((l) => l.label)).toEqual([
      "Attack detected",
      "Agent quarantined",
      "Workflow recovered",
      "Tests passed",
    ]);
  });

  it("is all lit after a full successful run", () => {
    const lights = verdictLights(deriveVerdict(fullRun()));
    expect(lights.map((l) => l.status)).toEqual(["lit", "lit", "lit", "lit"]);
  });

  it("shows a failed test run as failed rather than lit or pending", () => {
    nextSeq = 0;
    const verdict = deriveVerdict([
      event("TASK_COMPLETED", {
        metadata: { step: "pytest", detail: "1 failed", passed: false },
      }),
    ]);
    expect(verdictLights(verdict)[3].status).toBe("failed");
  });
});
