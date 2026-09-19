import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { foldEvents, loadReplayData } from "./loadReplayData";
import { initialGraphState, reduce, type Event, type SnapshotFrame } from "@/lib/stream/reducer";

const EXPERIMENT_ID = "exp-1";

function okResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body } as Response;
}

function errResponse(status: number) {
  return { ok: false, status, json: async () => ({}) } as Response;
}

const snapshotFrame: SnapshotFrame = {
  type: "snapshot",
  experiment_id: EXPERIMENT_ID,
  last_seq: 3,
  sim_tick: 0,
  status: "finished",
  nodes: [
    {
      id: "a",
      software_type: "sw-a",
      security_state: "compromised",
      tick_compromised: 0,
      agent_kind: "simulated",
    },
    { id: "b", software_type: "sw-a", security_state: "healthy", agent_kind: "simulated" },
  ],
  edges: [{ source: "a", target: "b" }],
};

function event(seq: number, tick: number): Event {
  return {
    event_id: `event-${seq}`,
    seq,
    sim_tick: tick,
    schema_version: 1,
    experiment_id: EXPERIMENT_ID,
    wall_time: "2026-01-01T00:00:00Z",
    event_type: "COMPROMISE_SUCCEEDED",
    source_agent_id: "a",
    target_agent_id: "b",
    metadata: {},
  };
}

describe("loadReplayData", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("folds the snapshot through reduce() and paginates events starting at snapshot.last_seq", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      const u = String(url);
      if (u.endsWith("/detail")) return okResponse({ is_complete: true });
      if (u.endsWith("/replay-snapshot")) return okResponse(snapshotFrame);
      if (u.includes("/events")) {
        const params = new URL(u).searchParams;
        const sinceSeq = Number(params.get("since_seq"));
        if (sinceSeq === 3) {
          return okResponse({ events: [event(4, 1), event(5, 1)], next_seq: 5 });
        }
        if (sinceSeq === 5) {
          return okResponse({ events: [event(6, 2)], next_seq: null });
        }
        throw new Error(`unexpected since_seq ${sinceSeq}`);
      }
      throw new Error(`unexpected fetch: ${u}`);
    });

    const data = await loadReplayData(EXPERIMENT_ID);

    expect(data.incomplete).toBe(false);
    expect(data.events.map((e) => e.seq)).toEqual([4, 5, 6]);
    // Never re-fetches/includes a tick-0 (seq <= last_seq) event.
    expect(data.events.every((e) => e.seq > snapshotFrame.last_seq)).toBe(true);

    const expectedInitialState = reduce(initialGraphState, snapshotFrame);
    expect(data.initialState).toEqual(expectedInitialState);
  });

  it.each([
    [true, false],
    [false, true],
    [null, true],
  ])("is_complete=%s -> incomplete=%s", async (isComplete, expectedIncomplete) => {
    fetchMock.mockImplementation(async (url: string) => {
      const u = String(url);
      if (u.endsWith("/detail")) return okResponse({ is_complete: isComplete });
      if (u.endsWith("/replay-snapshot")) return okResponse(snapshotFrame);
      if (u.includes("/events")) return okResponse({ events: [], next_seq: null });
      throw new Error(`unexpected fetch: ${u}`);
    });

    const data = await loadReplayData(EXPERIMENT_ID);
    expect(data.incomplete).toBe(expectedIncomplete);
  });

  it("propagates a fetch failure (e.g. 404 for an unknown experiment)", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      const u = String(url);
      if (u.endsWith("/detail")) return errResponse(404);
      throw new Error(`unexpected fetch: ${u}`);
    });

    await expect(loadReplayData(EXPERIMENT_ID)).rejects.toThrow("404");
  });
});

describe("foldEvents", () => {
  it("applies exactly `count` events in order, starting fresh from `from`", () => {
    const base = reduce(initialGraphState, snapshotFrame);
    const events = [event(4, 1), event(5, 1), event(6, 2)];

    const two = foldEvents(base, events, 2);
    let expected = base;
    expected = reduce(expected, { type: "event", event: events[0] });
    expected = reduce(expected, { type: "event", event: events[1] });
    expect(two).toEqual(expected);

    // Seeking backward is a fresh fold, not incremental undo.
    const zero = foldEvents(base, events, 0);
    expect(zero).toEqual(base);
  });

  it("clamps nothing itself -- callers are responsible for a valid count", () => {
    const base = reduce(initialGraphState, snapshotFrame);
    const events = [event(4, 1)];
    expect(foldEvents(base, events, 0)).toEqual(base);
  });
});
