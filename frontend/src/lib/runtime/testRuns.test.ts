import { describe, expect, it } from "vitest";

import type { Event } from "@/lib/stream/reducer";

import { deriveTestEvidence, parseCounts } from "./testRuns";

const SESSION = "99999999-9999-9999-9999-999999999999";

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

function pytest(detail: string, passed: boolean, command = "pytest demo_target"): Event {
  return event("TASK_COMPLETED", {
    agent_id: "developer",
    metadata: {
      step: "pytest",
      detail,
      passed,
      exit_code: passed ? 0 : 1,
      command,
    },
  });
}

describe("parseCounts", () => {
  it("reads pytest's own summary line", () => {
    expect(parseCounts("4 failed, 10 passed in 0.29s")).toEqual([
      { label: "failed", value: 4 },
      { label: "passed", value: 10 },
    ]);
    expect(parseCounts("14 passed in 0.13s")).toEqual([{ label: "passed", value: 14 }]);
  });

  it("reads errors and skips too", () => {
    expect(parseCounts("1 failed, 2 errors, 3 skipped in 1.1s")).toEqual([
      { label: "failed", value: 1 },
      { label: "errors", value: 2 },
      { label: "skipped", value: 3 },
    ]);
  });

  it("claims no counts at all from a line it cannot read", () => {
    expect(parseCounts("pytest timed out after 120s")).toEqual([]);
    expect(parseCounts("")).toEqual([]);
  });
});

describe("deriveTestEvidence", () => {
  it("is empty before any test has run", () => {
    nextSeq = 0;
    const evidence = deriveTestEvidence([
      event("TASK_COMPLETED", { metadata: { step: "patch", detail: "patched" } }),
    ]);
    expect(evidence.runs).toEqual([]);
    expect(evidence.before).toBeNull();
    expect(evidence.provedRed).toBe(false);
    expect(evidence.provedGreen).toBe(false);
  });

  it("keeps both runs of the real demo, red then green", () => {
    nextSeq = 0;
    const evidence = deriveTestEvidence([
      pytest("4 failed, 10 passed in 0.29s", false, "pytest demo_target  (before the fix)"),
      event("TASK_COMPLETED", { metadata: { step: "patch", detail: "patched" } }),
      pytest("14 passed in 0.13s", true),
    ]);
    expect(evidence.runs).toHaveLength(2);
    expect(evidence.before?.summary).toBe("4 failed, 10 passed in 0.29s");
    expect(evidence.after?.summary).toBe("14 passed in 0.13s");
    expect(evidence.provedRed).toBe(true);
    expect(evidence.provedGreen).toBe(true);
  });

  it("parses the counts off each run rather than hardcoding any", () => {
    nextSeq = 0;
    const evidence = deriveTestEvidence([
      pytest("3 failed, 15 passed in 1.16s", false),
      pytest("18 passed in 0.17s", true),
    ]);
    expect(evidence.before?.counts).toEqual([
      { label: "failed", value: 3 },
      { label: "passed", value: 15 },
    ]);
    expect(evidence.after?.counts).toEqual([{ label: "passed", value: 18 }]);
  });

  it("does not present a single run as a before/after pair", () => {
    nextSeq = 0;
    const evidence = deriveTestEvidence([pytest("14 passed in 0.13s", true)]);
    expect(evidence.before?.summary).toBe("14 passed in 0.13s");
    expect(evidence.after).toBeNull();
    expect(evidence.provedGreen).toBe(false);
    expect(evidence.provedRed).toBe(false);
  });

  it("reports a final red run as red", () => {
    nextSeq = 0;
    const evidence = deriveTestEvidence([
      pytest("4 failed, 10 passed in 0.29s", false),
      pytest("2 failed, 12 passed in 0.31s", false),
    ]);
    expect(evidence.after?.passed).toBe(false);
    expect(evidence.provedGreen).toBe(false);
  });

  it("keeps the command and exit code the run reported", () => {
    nextSeq = 0;
    const evidence = deriveTestEvidence([
      pytest("4 failed, 10 passed in 0.29s", false, "pytest demo_target  (before the fix)"),
    ]);
    expect(evidence.before?.command).toBe("pytest demo_target  (before the fix)");
    expect(evidence.before?.exitCode).toBe(1);
  });

  it("still surfaces a summary it cannot parse", () => {
    nextSeq = 0;
    const evidence = deriveTestEvidence([pytest("pytest timed out after 120s", false)]);
    expect(evidence.before?.summary).toBe("pytest timed out after 120s");
    expect(evidence.before?.counts).toEqual([]);
    expect(evidence.before?.passed).toBe(false);
  });
});
