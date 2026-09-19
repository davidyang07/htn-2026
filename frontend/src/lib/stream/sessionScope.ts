import type { ControlStatus } from "@/lib/controls/reducer";

/**
 * The live stream only ever carries what arrived over *this* WebSocket
 * connection: reconnecting to a run that has already finished yields a fresh
 * snapshot and nothing else (docs/SPEC.md §4). That is correct behaviour, but
 * "no events yet" is the wrong thing to tell someone looking at a completed
 * run — this is the honest explanation, used everywhere the live log or the
 * live-derived curve is empty.
 */
export function liveLogGapHint(status: ControlStatus, hasEvents: boolean): string | undefined {
  if (hasEvents) return undefined;
  if (status === "finished" || status === "stopped") {
    return "This run has already ended, and the live stream only carries events received while connected. Open it under Runs to replay its complete recorded log.";
  }
  return undefined;
}
