import { describe, expect, it } from "vitest";

import type { RuntimeSessionSummary, WorkerView } from "@/lib/runtime/client";
import { initialGraphState, type GraphState, type NodeView } from "@/lib/stream/reducer";

import { buildSwarmModel } from "./swarmModel";

const SESSION = "44444444-4444-4444-4444-444444444444";

function worker(
  id: string,
  role: string,
  overrides: Partial<WorkerView> = {},
): WorkerView {
  return {
    id,
    role,
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
    objective: "Fix the auth bug.",
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

function streamWith(nodes: NodeView[], sessionId = SESSION): GraphState {
  return {
    ...initialGraphState,
    experimentId: sessionId,
    nodes: new Map(nodes.map((n) => [n.id, n])),
  };
}

const TEAM = [
  worker("repo-analyst", "Repo Analyst"),
  worker("security-researcher", "Security Researcher", { upstream: ["repo-analyst"] }),
  worker("developer", "Developer", { upstream: ["security-researcher"] }),
  worker("reviewer", "Reviewer", { upstream: ["developer"] }),
];

describe("buildSwarmModel", () => {
  it("is empty with no session", () => {
    const model = buildSwarmModel(null, initialGraphState);
    expect(model.nodes).toEqual([]);
    expect(model.edges).toEqual([]);
  });

  it("draws the team from the summary, with roles as the node type", () => {
    const model = buildSwarmModel(summary(TEAM), initialGraphState);
    expect(model.nodes.map((n) => n.id)).toEqual([
      "repo-analyst",
      "security-researcher",
      "developer",
      "reviewer",
    ]);
    expect(model.nodes.map((n) => n.attrs.software_type)).toEqual([
      "Repo Analyst",
      "Security Researcher",
      "Developer",
      "Reviewer",
    ]);
    expect(model.nodes.every((n) => n.attrs.agent_kind === "real")).toBe(true);
    expect(model.edges.map((e) => `${e.source}->${e.target}`)).toEqual([
      "repo-analyst->security-researcher",
      "security-researcher->developer",
      "developer->reviewer",
    ]);
  });

  it("draws a replacement worker the stream has never snapshotted", () => {
    // The whole reason this module exists: a client attached before the
    // replacement was created has it in the summary but not in the stream.
    const withReplacement = [
      ...TEAM,
      worker("replacement-researcher", "Replacement Researcher", {
        upstream: ["repo-analyst"],
        replaces: "security-researcher",
      }),
    ];
    const staleStream = streamWith(
      TEAM.map((w) => ({
        id: w.id,
        software_type: w.role,
        security_state: "healthy" as const,
        agent_kind: "real" as const,
      })),
    );

    const model = buildSwarmModel(summary(withReplacement), staleStream);
    expect(model.nodes.map((n) => n.id)).toContain("replacement-researcher");
  });

  it("routes the replacement into the handoffs of the worker it replaced", () => {
    const withReplacement = [
      ...TEAM,
      worker("replacement-researcher", "Replacement Researcher", {
        upstream: ["repo-analyst"],
        replaces: "security-researcher",
      }),
    ];
    const model = buildSwarmModel(summary(withReplacement), initialGraphState);
    const edges = model.edges.map((e) => `${e.source}->${e.target}`);

    expect(edges).toContain("repo-analyst->replacement-researcher");
    // The developer declared its upstream at creation and cannot re-declare
    // it; the replacement inherits the handoff so the recovery is visible.
    expect(edges).toContain("replacement-researcher->developer");
    // The quarantined worker stays in the graph with its original edges.
    expect(edges).toContain("security-researcher->developer");
  });

  it("prefers the stream's security state over the poll's", () => {
    const stream = streamWith([
      {
        id: "security-researcher",
        software_type: "Security Researcher",
        security_state: "quarantined",
        agent_kind: "real",
      },
    ]);
    const model = buildSwarmModel(summary(TEAM), stream);
    const node = model.nodes.find((n) => n.id === "security-researcher");
    expect(node?.securityState).toBe("quarantined");
  });

  it("ignores a stream attached to a different session", () => {
    const stream = streamWith(
      [
        {
          id: "security-researcher",
          software_type: "Security Researcher",
          security_state: "quarantined",
          agent_kind: "real",
        },
      ],
      "99999999-9999-9999-9999-999999999999",
    );
    const model = buildSwarmModel(summary(TEAM), stream);
    expect(model.nodes.find((n) => n.id === "security-researcher")?.securityState).toBe(
      "healthy",
    );
  });

  it("never emits an edge to a worker that does not exist", () => {
    const model = buildSwarmModel(
      summary([worker("developer", "Developer", { upstream: ["ghost"] })]),
      initialGraphState,
    );
    expect(model.edges).toEqual([]);
  });

  it("keys the layout on structure only, so a poll does not relayout", () => {
    const a = buildSwarmModel(summary(TEAM), initialGraphState);
    const churned = summary(
      TEAM.map((w) => worker(w.id, w.role, { ...w, current_task: "something new" })),
    );
    expect(buildSwarmModel(churned, initialGraphState).structureKey).toBe(a.structureKey);

    const grown = summary([...TEAM, worker("replacement-researcher", "Replacement")]);
    expect(buildSwarmModel(grown, initialGraphState).structureKey).not.toBe(a.structureKey);
  });
});
