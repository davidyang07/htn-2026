import { describe, expect, it } from "vitest";
import {
  EVENT_LOG_CAP,
  INCIDENT_LOG_CAP,
  initialGraphState,
  reduce,
  selectMetrics,
  type Event,
  type EventFrame,
  type NodeView,
  type SnapshotFrame,
} from "./reducer";

const EXPERIMENT_A = "11111111-1111-1111-1111-111111111111";
const EXPERIMENT_B = "22222222-2222-2222-2222-222222222222";

function node(id: string, security_state: NodeView["security_state"] = "healthy"): NodeView {
  return { id, software_type: "sw-a", security_state, agent_kind: "simulated" };
}

function snapshot(overrides: Partial<SnapshotFrame> = {}): SnapshotFrame {
  return {
    type: "snapshot",
    experiment_id: EXPERIMENT_A,
    last_seq: -1,
    sim_tick: 0,
    status: "running",
    nodes: [node("agent-000"), node("agent-001")],
    edges: [{ source: "agent-000", target: "agent-001" }],
    ...overrides,
  };
}

function event(
  overrides: Partial<Event> & Pick<Event, "event_type" | "sim_tick" | "seq">,
): Event {
  return {
    event_id: `event-${overrides.seq}`,
    schema_version: 1,
    experiment_id: EXPERIMENT_A,
    wall_time: "2024-01-01T00:00:00Z",
    metadata: {},
    ...overrides,
  };
}

function evFrame(e: Event): EventFrame {
  return { type: "event", event: e };
}

describe("snapshot", () => {
  it("initializes experiment id, tick, lastSeq, nodes, edges", () => {
    const state = reduce(initialGraphState, snapshot());

    expect(state.experimentId).toBe(EXPERIMENT_A);
    expect(state.tick).toBe(0);
    expect(state.lastSeq).toBe(-1);
    expect(state.nodes.size).toBe(2);
    expect(state.edges).toEqual([{ source: "agent-000", target: "agent-001" }]);
  });

  it("derives correct metrics from a snapshot containing pre-existing compromised/quarantined nodes", () => {
    const state = reduce(
      initialGraphState,
      snapshot({
        nodes: [
          node("agent-000", "healthy"),
          node("agent-001", "compromised"),
          node("agent-002", "quarantined"),
        ],
      }),
    );

    expect(selectMetrics(state)).toMatchObject({
      total: 3,
      healthy: 1,
      compromised: 1,
      quarantined: 1,
      totalExposure: 2,
      // Regression: a fresh experiment's very first snapshot can already
      // show compromised/quarantined nodes (the seeded patient-zero
      // compromise always happens before any client can connect). This
      // must be reflected in newCompromises immediately, not only once a
      // live event happens to arrive after connection — see the dedicated
      // "patient zero" test below for the exact scenario this guards.
      newCompromises: 2,
      outbreakDuration: 0,
    });
  });

  it("counts the seeded patient-zero compromise in newCompromises on first connect, with no live event required", () => {
    const state = reduce(
      initialGraphState,
      snapshot({ nodes: [node("agent-000", "compromised"), node("agent-001", "healthy")] }),
    );

    expect(selectMetrics(state).newCompromises).toBe(1);
    expect(selectMetrics(state).totalExposure).toBe(1);
  });

  it("does not double-count the snapshot baseline once live events continue the run", () => {
    let state = reduce(
      initialGraphState,
      snapshot({ nodes: [node("agent-000", "compromised"), node("agent-001", "healthy")] }),
    );
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 1,
          seq: 0,
          source_agent_id: "agent-000",
          target_agent_id: "agent-001",
        }),
      ),
    );

    expect(selectMetrics(state).newCompromises).toBe(2);
    expect(selectMetrics(state).totalExposure).toBe(2);
  });
});

describe("compromise", () => {
  it("sets the target to compromised and counts a new compromise", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 1,
          seq: 1,
          source_agent_id: "agent-000",
          target_agent_id: "agent-001",
        }),
      ),
    );

    expect(state.nodes.get("agent-001")?.security_state).toBe("compromised");
    expect(selectMetrics(state).newCompromises).toBe(1);
    expect(selectMetrics(state).totalExposure).toBe(1);
  });

  it("does not double-count a same-tick already_compromised claim", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 1,
          seq: 1,
          source_agent_id: "agent-000",
          target_agent_id: "agent-001",
        }),
      ),
    );
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 1,
          seq: 2,
          source_agent_id: "agent-000",
          target_agent_id: "agent-001",
          metadata: { already_compromised: true },
        }),
      ),
    );

    expect(selectMetrics(state).newCompromises).toBe(1);
    expect(selectMetrics(state).totalExposure).toBe(1);
  });

  it("sets compromised_by and tick_compromised on the target node", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 5,
          seq: 1,
          source_agent_id: "agent-000",
          target_agent_id: "agent-001",
        }),
      ),
    );

    const targetNode = state.nodes.get("agent-001");
    expect(targetNode?.compromised_by).toBe("agent-000");
    expect(targetNode?.tick_compromised).toBe(5);
  });

  it("keeps first-claim compromised_by/tick_compromised when a duplicate already_compromised claim arrives", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 5,
          seq: 1,
          source_agent_id: "attacker-A",
          target_agent_id: "agent-001",
        }),
      ),
    );
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 5,
          seq: 2,
          source_agent_id: "attacker-B",
          target_agent_id: "agent-001",
          metadata: { already_compromised: true },
        }),
      ),
    );

    const targetNode = state.nodes.get("agent-001");
    expect(targetNode?.security_state).toBe("compromised");
    expect(targetNode?.compromised_by).toBe("attacker-A");
    expect(targetNode?.tick_compromised).toBe(5);
  });

  it("does not affect an unrelated node when a compromise event is applied", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 3,
          seq: 1,
          source_agent_id: "agent-000",
          target_agent_id: "agent-001",
        }),
      ),
    );

    const unrelatedNode = state.nodes.get("agent-000");
    expect(unrelatedNode?.security_state).toBe("healthy");
    expect(unrelatedNode?.compromised_by).toBeUndefined();
    expect(unrelatedNode?.tick_compromised).toBeUndefined();
  });
});

describe("detection", () => {
  it("records an incident without changing security_state", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "ANOMALY_DETECTED",
          sim_tick: 1,
          seq: 1,
          agent_id: "agent-000",
          metadata: { sensitivity: 0.5 },
        }),
      ),
    );

    expect(state.nodes.get("agent-000")?.security_state).toBe("healthy");
    expect(state.incidentsByAgent.get("agent-000")?.map((e) => e.event_type)).toEqual([
      "ANOMALY_DETECTED",
    ]);
  });
});

describe("quarantine", () => {
  it("moves the node from compromised to quarantined via agent_id and updates derived metrics", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 1,
          seq: 1,
          source_agent_id: "agent-000",
          target_agent_id: "agent-001",
        }),
      ),
    );
    expect(selectMetrics(state)).toMatchObject({ compromised: 1, quarantined: 0 });

    state = reduce(
      state,
      evFrame(
        event({ event_type: "AGENT_QUARANTINED", sim_tick: 2, seq: 2, agent_id: "agent-001" }),
      ),
    );

    expect(state.nodes.get("agent-001")?.security_state).toBe("quarantined");
    expect(selectMetrics(state)).toMatchObject({ compromised: 0, quarantined: 1, totalExposure: 1 });
    expect(
      state.incidentsByAgent.get("agent-001")?.some((e) => e.event_type === "AGENT_QUARANTINED"),
    ).toBe(true);
  });

  it("no-ops when the node does not exist", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(
        event({ event_type: "AGENT_QUARANTINED", sim_tick: 1, seq: 1, agent_id: "agent-999" }),
      ),
    );

    expect(state.nodes.has("agent-999")).toBe(false);
  });
});

describe("multiple ordered events", () => {
  it("produces the exact expected final projection", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_ATTEMPTED",
          sim_tick: 1,
          seq: 1,
          source_agent_id: "agent-000",
          target_agent_id: "agent-001",
          metadata: { probability: 0.8 },
        }),
      ),
    );
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 1,
          seq: 2,
          source_agent_id: "agent-000",
          target_agent_id: "agent-001",
          metadata: { probability: 0.8 },
        }),
      ),
    );
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "ANOMALY_DETECTED",
          sim_tick: 2,
          seq: 3,
          agent_id: "agent-001",
          metadata: { sensitivity: 0.5 },
        }),
      ),
    );
    state = reduce(
      state,
      evFrame(
        event({ event_type: "AGENT_QUARANTINED", sim_tick: 2, seq: 4, agent_id: "agent-001" }),
      ),
    );

    expect(state.nodes.get("agent-001")?.security_state).toBe("quarantined");
    expect(selectMetrics(state)).toMatchObject({
      total: 2,
      healthy: 1,
      compromised: 0,
      quarantined: 1,
      totalExposure: 1,
      newCompromises: 1,
      outbreakDuration: 2,
    });
    expect(state.incidentsByAgent.get("agent-001")?.map((e) => e.event_type)).toEqual([
      "COMPROMISE_ATTEMPTED",
      "COMPROMISE_SUCCEEDED",
      "ANOMALY_DETECTED",
      "AGENT_QUARANTINED",
    ]);
    expect(state.incidentsByAgent.get("agent-000")?.map((e) => e.event_type)).toEqual([
      "COMPROMISE_ATTEMPTED",
      "COMPROMISE_SUCCEEDED",
    ]);
  });
});

describe("cumulative-history safety", () => {
  it("does not erase new compromises when later ticks contain other events", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 1,
          seq: 1,
          source_agent_id: "agent-000",
          target_agent_id: "agent-001",
        }),
      ),
    );
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "ANOMALY_DETECTED",
          sim_tick: 2,
          seq: 2,
          agent_id: "agent-001",
        }),
      ),
    );

    expect(selectMetrics(state).newCompromises).toBe(1);
  });

  it("keeps recentEvents capped at 200 while derived cumulative metrics stay correct", () => {
    let state = reduce(initialGraphState, snapshot());
    let seq = 1;
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 1,
          seq: seq++,
          source_agent_id: "agent-000",
          target_agent_id: "agent-001",
        }),
      ),
    );
    for (let i = 0; i < 250; i++) {
      state = reduce(
        state,
        evFrame(
          event({
            event_type: "ANOMALY_DETECTED",
            sim_tick: 2 + i,
            seq: seq++,
            agent_id: "agent-000",
            metadata: { sensitivity: 0.1 },
          }),
        ),
      );
    }

    expect(state.recentEvents.length).toBe(EVENT_LOG_CAP);
    expect(selectMetrics(state).totalExposure).toBe(1);
    expect(state.nodes.get("agent-001")?.security_state).toBe("compromised");
  });

  it("caps incidentsByAgent at INCIDENT_LOG_CAP per agent", () => {
    let state = reduce(initialGraphState, snapshot({ nodes: [node("agent-000")], edges: [] }));
    let seq = 1;
    for (let i = 0; i < 60; i++) {
      state = reduce(
        state,
        evFrame(
          event({
            event_type: "ANOMALY_DETECTED",
            sim_tick: 1 + i,
            seq: seq++,
            agent_id: "agent-000",
            metadata: { sensitivity: 0.1 },
          }),
        ),
      );
    }

    expect(state.incidentsByAgent.get("agent-000")?.length).toBe(INCIDENT_LOG_CAP);
  });
});

describe("new experiment / fresh snapshot", () => {
  it("does not leak prior-experiment state into a replacement experiment", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 1,
          seq: 1,
          source_agent_id: "agent-000",
          target_agent_id: "agent-001",
        }),
      ),
    );
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "ANOMALY_DETECTED",
          sim_tick: 1,
          seq: 2,
          agent_id: "agent-001",
          metadata: {},
        }),
      ),
    );

    const next = reduce(
      state,
      snapshot({
        experiment_id: EXPERIMENT_B,
        last_seq: -1,
        sim_tick: 0,
        nodes: [node("agent-000")],
        edges: [],
      }),
    );

    expect(next.experimentId).toBe(EXPERIMENT_B);
    expect(next.recentEvents).toEqual([]);
    expect(next.incidentsByAgent.size).toBe(0);
    expect(selectMetrics(next)).toMatchObject({ newCompromises: 0, totalExposure: 0 });
  });
});

describe("same-experiment reconnect snapshot", () => {
  it("preserves accumulated metrics/incidents/recentEvents while replacing nodes/edges/tick/lastSeq", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 1,
          seq: 1,
          source_agent_id: "agent-000",
          target_agent_id: "agent-001",
        }),
      ),
    );
    state = reduce(
      state,
      evFrame(
        event({ event_type: "AGENT_QUARANTINED", sim_tick: 2, seq: 2, agent_id: "agent-001" }),
      ),
    );

    const reconnected = reduce(
      state,
      snapshot({
        experiment_id: EXPERIMENT_A,
        last_seq: 2,
        sim_tick: 2,
        nodes: [node("agent-000"), node("agent-001", "quarantined")],
      }),
    );

    expect(reconnected.recentEvents).toEqual(state.recentEvents);
    expect(reconnected.incidentsByAgent).toEqual(state.incidentsByAgent);
    expect(reconnected.lastSeq).toBe(2);
    expect(reconnected.nodes.get("agent-001")?.security_state).toBe("quarantined");
    expect(selectMetrics(reconnected).totalExposure).toBe(1);
  });
});

describe("unknown event type", () => {
  it("appends to recentEvents without mutating node/metrics/incident state", () => {
    let state = reduce(initialGraphState, snapshot());
    const nodesBefore = state.nodes;

    state = reduce(
      state,
      evFrame(event({ event_type: "AGENT_RECOVERED", sim_tick: 1, seq: 1, agent_id: "agent-000" })),
    );

    expect(state.nodes).toBe(nodesBefore);
    expect(state.recentEvents).toHaveLength(1);
    expect(state.incidentsByAgent.size).toBe(0);
    expect(selectMetrics(state).newCompromises).toBe(0);
  });
});

describe("unknown schema version", () => {
  it("throws rather than silently skipping the frame", () => {
    const state = reduce(initialGraphState, snapshot());

    expect(() =>
      reduce(
        state,
        evFrame(
          event({ event_type: "AGENT_CREATED", sim_tick: 1, seq: 1, schema_version: 2 }),
        ),
      ),
    ).toThrow();
  });
});

describe("phase 2 model/tool events", () => {
  it("increments modelCalls on MODEL_REQUESTED and appears in recentEvents", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "MODEL_REQUESTED",
          sim_tick: 1,
          seq: 1,
          agent_id: "agent-001",
          metadata: { source_agent_id: "agent-000" },
        }),
      ),
    );

    expect(selectMetrics(state).modelCalls).toBe(1);
    expect(state.recentEvents).toHaveLength(1);
  });

  it("does not increment modelCalls on MODEL_RESPONDED or TOOL_EXECUTED", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(event({ event_type: "MODEL_RESPONDED", sim_tick: 1, seq: 1, agent_id: "agent-001" })),
    );
    state = reduce(
      state,
      evFrame(event({ event_type: "TOOL_EXECUTED", sim_tick: 1, seq: 2, agent_id: "agent-001" })),
    );

    expect(selectMetrics(state).modelCalls).toBe(0);
  });

  it("MODEL_REQUESTED/MODEL_RESPONDED/TOOL_EXECUTED are not security incidents", () => {
    let state = reduce(initialGraphState, snapshot());
    const types = ["MODEL_REQUESTED", "MODEL_RESPONDED", "TOOL_EXECUTED"] as const;
    for (const [i, type] of types.entries()) {
      state = reduce(
        state,
        evFrame(event({ event_type: type, sim_tick: 1, seq: i + 1, agent_id: "agent-001" })),
      );
    }

    expect(state.incidentsByAgent.size).toBe(0);
  });

  it("modelCalls resets to 0 on a fresh (different-experiment) snapshot, preserved across a same-experiment reconnect", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(event({ event_type: "MODEL_REQUESTED", sim_tick: 1, seq: 1, agent_id: "agent-001" })),
    );
    expect(selectMetrics(state).modelCalls).toBe(1);

    const reconnected = reduce(state, snapshot({ last_seq: 1 }));
    expect(selectMetrics(reconnected).modelCalls).toBe(1);

    const fresh = reduce(state, snapshot({ experiment_id: EXPERIMENT_B, last_seq: -1 }));
    expect(selectMetrics(fresh).modelCalls).toBe(0);
  });

  it("COMPROMISE_SUCCEEDED still increments newCompromises after a MODEL_REQUESTED event (metrics object is not clobbered)", () => {
    let state = reduce(initialGraphState, snapshot());
    state = reduce(
      state,
      evFrame(event({ event_type: "MODEL_REQUESTED", sim_tick: 1, seq: 1, agent_id: "agent-001" })),
    );
    state = reduce(
      state,
      evFrame(
        event({
          event_type: "COMPROMISE_SUCCEEDED",
          sim_tick: 1,
          seq: 2,
          source_agent_id: "agent-000",
          target_agent_id: "agent-001",
        }),
      ),
    );

    expect(selectMetrics(state).modelCalls).toBe(1);
    expect(selectMetrics(state).newCompromises).toBe(1);
  });
});
