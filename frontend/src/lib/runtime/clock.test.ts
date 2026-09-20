import { describe, expect, it } from "vitest";

import type { Event } from "@/lib/stream/reducer";

import { elapsedMs, formatDuration, runWindow } from "./clock";

const SESSION = "55555555-5555-5555-5555-555555555555";

function at(iso: string, seq: number): Event {
  return {
    event_id: `event-${seq}`,
    seq,
    schema_version: 1,
    experiment_id: SESSION,
    wall_time: iso,
    sim_tick: seq,
    event_type: "TASK_COMPLETED" as Event["event_type"],
    metadata: {},
  };
}

describe("runWindow", () => {
  it("is empty before any event arrives", () => {
    expect(runWindow([])).toEqual({ startedAt: null, lastEventAt: null });
  });

  it("spans the first and last recorded wall times", () => {
    const window = runWindow([
      at("2026-03-02T00:00:00Z", 0),
      at("2026-03-02T00:02:30Z", 1),
    ]);
    expect(window.startedAt).toBe(Date.parse("2026-03-02T00:00:00Z"));
    expect(window.lastEventAt).toBe(Date.parse("2026-03-02T00:02:30Z"));
  });

  it("ignores an unparseable timestamp rather than producing NaN", () => {
    const window = runWindow([at("not-a-date", 0), at("2026-03-02T00:01:00Z", 1)]);
    expect(window.startedAt).toBe(Date.parse("2026-03-02T00:01:00Z"));
  });
});

describe("elapsedMs", () => {
  const window = runWindow([at("2026-03-02T00:00:00Z", 0), at("2026-03-02T00:02:30Z", 1)]);

  it("freezes a finished run at its last event, not at now", () => {
    const now = Date.parse("2026-03-02T09:00:00Z");
    expect(elapsedMs(window, { live: false, now })).toBe(150_000);
  });

  it("runs to now while the run is live", () => {
    const now = Date.parse("2026-03-02T00:04:00Z");
    expect(elapsedMs(window, { live: true, now })).toBe(240_000);
  });

  it("has nothing to report before the first event", () => {
    expect(elapsedMs({ startedAt: null, lastEventAt: null }, { live: true, now: 0 })).toBeNull();
  });
});

describe("formatDuration", () => {
  it("formats minutes and seconds", () => {
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(7_000)).toBe("0:07");
    expect(formatDuration(239_000)).toBe("3:59");
  });

  it("grows an hours field only when it needs one", () => {
    expect(formatDuration(3_600_000)).toBe("1:00:00");
    expect(formatDuration(3_671_000)).toBe("1:01:11");
  });

  it("renders an em dash when there is nothing to time", () => {
    expect(formatDuration(null)).toBe("—");
  });
});
