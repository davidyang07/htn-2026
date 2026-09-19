import { describe, expect, it } from "vitest";

import {
  type Event,
  type SnapshotFrame,
  initialGraphState,
  reduce,
  selectMetrics,
} from "@/lib/stream/reducer";

const EXPERIMENT_ID = "11111111-1111-1111-1111-111111111111";

function agentCreated(seq: number, agentId: string): Event {
  return {
    event_id: `event-${seq}`,
    seq,
    sim_tick: 0,
    schema_version: 1,
    experiment_id: EXPERIMENT_ID,
    wall_time: "2026-01-01T00:00:00Z",
    event_type: "AGENT_CREATED",
    agent_id: agentId,
    metadata: { software_type: "sw-a" },
  };
}

function seedCompromise(seq: number, targetId: string): Event {
  return {
    event_id: `event-${seq}`,
    seq,
    sim_tick: 0,
    schema_version: 1,
    experiment_id: EXPERIMENT_ID,
    wall_time: "2026-01-01T00:00:00Z",
    event_type: "COMPROMISE_SUCCEEDED",
    target_agent_id: targetId,
    metadata: { initial_compromise: true },
  };
}

function followupCompromise(seq: number, tick: number, source: string, target: string): Event {
  return {
    event_id: `event-${seq}`,
    seq,
    sim_tick: tick,
    schema_version: 1,
    experiment_id: EXPERIMENT_ID,
    wall_time: "2026-01-01T00:00:01Z",
    event_type: "COMPROMISE_SUCCEEDED",
    source_agent_id: source,
    target_agent_id: target,
    metadata: {},
  };
}

describe("replay/live reduce() equivalence", () => {
  const nodeIds = ["agent-000", "agent-001", "agent-002"];
  const seedId = "agent-000";

  // The tick-0 events a literal re-simulation would have produced. These
  // must never be re-delivered through the event branch once the snapshot
  // already reflects them -- the verified double-counting hazard from
  // docs/PHASE_1_5_PLAN.md §7.
  const tick0Events: Event[] = [
    ...nodeIds.map((id, i) => agentCreated(i, id)),
    seedCompromise(nodeIds.length, seedId),
  ];
  const lastTick0Seq = tick0Events[tick0Events.length - 1].seq;

  const snapshot: SnapshotFrame = {
    type: "snapshot",
    experiment_id: EXPERIMENT_ID,
    last_seq: lastTick0Seq,
    sim_tick: 0,
    status: "running",
    nodes: nodeIds.map((id) => ({
      id,
      software_type: "sw-a",
      security_state: id === seedId ? "compromised" : "healthy",
      tick_compromised: id === seedId ? 0 : null,
      agent_kind: "simulated",
    })),
    edges: [{ source: nodeIds[0], target: nodeIds[1] }],
  };

  const postCutoffEvents: Event[] = [
    followupCompromise(lastTick0Seq + 1, 1, "agent-000", "agent-002"),
  ];

  it("live-style connect-after-tick-0 and replay-style snapshot+post-cutoff fold produce identical GraphState", () => {
    // Live-style: a WS client that connects after tick 0 only ever receives
    // the snapshot (already reflecting the seed compromise) plus events
    // from here on -- it never sees tick0Events directly.
    let liveState = reduce(initialGraphState, snapshot);
    for (const event of postCutoffEvents) {
      liveState = reduce(liveState, { type: "event", event });
    }

    // Replay-style: the exact fold useReplayStream performs -- snapshot,
    // then only events with seq > snapshot.last_seq, mirroring the
    // backend's replay-snapshot MAX(seq) WHERE sim_tick=0 cutoff.
    const allEvents = [...tick0Events, ...postCutoffEvents];
    let replayState = reduce(initialGraphState, snapshot);
    for (const event of allEvents.filter((e) => e.seq > snapshot.last_seq)) {
      replayState = reduce(replayState, { type: "event", event });
    }

    const strip = (s: typeof liveState) => ({
      nodes: s.nodes,
      edges: s.edges,
      metrics: s.metrics,
      incidentsByAgent: s.incidentsByAgent,
      tick: s.tick,
      lastSeq: s.lastSeq,
    });
    expect(strip(replayState)).toEqual(strip(liveState));

    // Direct regression assertion: exactly one count for the seeded patient
    // zero (from snapshot-seeding) plus one for the follow-up compromise --
    // never a second count for the same seed node.
    expect(selectMetrics(replayState).newCompromises).toBe(2);
  });

  it("documents the hazard: re-delivering tick0Events after the snapshot double-counts the seed compromise", () => {
    // What a wrong cutoff (e.g. since_seq=-1 instead of snapshot.last_seq)
    // would produce -- proves the seq > last_seq cutoff is load-bearing,
    // not cosmetic.
    const allEvents = [...tick0Events, ...postCutoffEvents];
    let buggyState = reduce(initialGraphState, snapshot);
    for (const event of allEvents) {
      buggyState = reduce(buggyState, { type: "event", event });
    }
    expect(selectMetrics(buggyState).newCompromises).toBe(3);
  });
});
