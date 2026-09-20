// How long the run has been going, from the events themselves.
//
// The wall clock comes off `Event.wall_time` rather than from a timer started
// when the page opened: /demo is routinely opened *after* a run has finished,
// and a stopwatch that starts on page load would report the age of the tab as
// the length of the run.

import type { Event } from "@/lib/stream/reducer";

export type RunWindow = {
  /** Epoch ms of the first recorded event, or null before any arrive. */
  startedAt: number | null;
  /** Epoch ms of the last recorded event. */
  lastEventAt: number | null;
};

function epoch(iso: string): number | null {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
}

export function runWindow(events: readonly Event[]): RunWindow {
  let startedAt: number | null = null;
  let lastEventAt: number | null = null;

  for (const event of events) {
    const ms = epoch(event.wall_time);
    if (ms === null) continue;
    if (startedAt === null || ms < startedAt) startedAt = ms;
    if (lastEventAt === null || ms > lastEventAt) lastEventAt = ms;
  }

  return { startedAt, lastEventAt };
}

/**
 * Elapsed run time in ms.
 *
 * While the run is live the clock runs to `now`; once it has finished it
 * freezes at the last event, so a completed run reports how long it took and
 * not how long ago it was.
 */
export function elapsedMs(
  window: RunWindow,
  { live, now }: { live: boolean; now: number },
): number | null {
  if (window.startedAt === null) return null;
  const end = live ? now : (window.lastEventAt ?? window.startedAt);
  return Math.max(0, end - window.startedAt);
}

/** `m:ss`, or `h:mm:ss` past an hour. Monospace-safe and never rounds up. */
export function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  const total = Math.floor(ms / 1000);
  const seconds = total % 60;
  const minutes = Math.floor(total / 60) % 60;
  const hours = Math.floor(total / 3600);
  const mm = String(minutes).padStart(hours > 0 ? 2 : 1, "0");
  const ss = String(seconds).padStart(2, "0");
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}
