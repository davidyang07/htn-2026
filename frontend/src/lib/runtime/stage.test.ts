import { describe, expect, it } from "vitest";

import type { RuntimeSessionSummary, WorkerView } from "@/lib/runtime/client";
import { initialGraphState } from "@/lib/stream/reducer";

import { buildStage, EMPTY_STAGE } from "./stage";

const SESSION = "66666666-6666-6666-6666-666666666666";

function worker(id: string, overrides: Partial<WorkerView> = {}): WorkerView {
  return {
    id,
    role: id,
    security_state: "healthy",
    current_task: null,
    upstream: [],
    replaces: null,
    model_backed: false,
    quarantine_reason: null,
    step_quarantined: null,
    ...overrides,
  };
}

function summary(workers: WorkerView[]): RuntimeSessionSummary {
  return {
    session_id: SESSION,
    objective: "objective",
    workflow_state: "running",
    step: 1,
    last_seq: 1,
    attack_detected: false,
    recovery_required: false,
    model_calls: 0,
    tests_passed: null,
    test_summary: null,
    workers,
    artifacts: [],
  };
}

/** The team the Live Swarm Demo actually registers. */
function demoTeam(): WorkerView[] {
  return [
    worker("repo-analyst", { role: "Repo Analyst" }),
    worker("security-researcher", {
      role: "Security Researcher",
      upstream: ["repo-analyst"],
      security_state: "quarantined",
      quarantine_reason: "demo_target/secrets/ is a protected directory.",
    }),
    worker("developer", { role: "Developer", upstream: ["security-researcher"] }),
    worker("reviewer", { role: "Reviewer", upstream: ["developer"] }),
    worker("replacement-researcher", {
      role: "Replacement Researcher",
      upstream: ["repo-analyst"],
      replaces: "security-researcher",
      security_state: "recovered",
    }),
  ];
}

describe("buildStage", () => {
  it("is empty with no session", () => {
    expect(buildStage(null, initialGraphState)).toBe(EMPTY_STAGE);
    expect(buildStage(summary([]), initialGraphState)).toBe(EMPTY_STAGE);
  });

  it("orders the chain by handoff depth", () => {
    const stage = buildStage(summary(demoTeam()), initialGraphState);
    expect(stage.columns.map((c) => c.nodes.map((n) => n.id))).toEqual([
      ["repo-analyst"],
      ["security-researcher", "replacement-researcher"],
      ["developer"],
      ["reviewer"],
    ]);
  });

  it("puts a replacement beside its predecessor, never one step later", () => {
    const stage = buildStage(summary(demoTeam()), initialGraphState);
    const quarantined = stage.columns[1]?.nodes[0];
    const replacement = stage.columns[1]?.nodes[1];
    expect(quarantined?.id).toBe("security-researcher");
    expect(replacement?.id).toBe("replacement-researcher");
    expect(replacement?.column).toBe(quarantined?.column);
  });

  it("renders the replacement below its predecessor whatever order it is reported in", () => {
    const reordered = demoTeam();
    const [replacement] = reordered.splice(4, 1);
    reordered.unshift(replacement!);
    const stage = buildStage(summary(reordered), initialGraphState);
    expect(stage.columns[1]?.nodes.map((n) => n.id)).toEqual([
      "security-researcher",
      "replacement-researcher",
    ]);
  });

  it("maps the quarantined worker to whoever took its task", () => {
    const stage = buildStage(summary(demoTeam()), initialGraphState);
    expect(stage.reassignments.get("security-researcher")).toBe("replacement-researcher");
    expect(stage.breached).toBe(true);
  });

  it("is unbreached while every worker is healthy", () => {
    const healthy = demoTeam()
      .filter((w) => w.replaces === null)
      .map((w) => ({ ...w, security_state: "healthy" as const, quarantine_reason: null }));
    const stage = buildStage(summary(healthy), initialGraphState);
    expect(stage.breached).toBe(false);
    expect(stage.reassignments.size).toBe(0);
  });

  it("prefers the stream's security state over the poll's", () => {
    const stream = {
      ...initialGraphState,
      experimentId: SESSION,
      nodes: new Map([
        [
          "developer",
          {
            id: "developer",
            security_state: "compromised" as const,
            node_type: "agent" as const,
            attrs: {},
          },
        ],
      ]),
    } as unknown as typeof initialGraphState;
    const stage = buildStage(summary(demoTeam()), stream);
    const developer = stage.columns.flatMap((c) => c.nodes).find((n) => n.id === "developer");
    expect(developer?.securityState).toBe("compromised");
  });

  it("terminates on a cycle instead of hanging the screen", () => {
    const cyclic = [
      worker("a", { upstream: ["b"] }),
      worker("b", { upstream: ["a"] }),
    ];
    const stage = buildStage(summary(cyclic), initialGraphState);
    expect(stage.columns.flatMap((c) => c.nodes)).toHaveLength(2);
  });

  it("ignores an upstream worker that is not in the team", () => {
    const stage = buildStage(
      summary([worker("solo", { upstream: ["ghost"] })]),
      initialGraphState,
    );
    expect(stage.columns).toEqual([
      { column: 0, nodes: [expect.objectContaining({ id: "solo", column: 0 })] },
    ]);
  });
});
