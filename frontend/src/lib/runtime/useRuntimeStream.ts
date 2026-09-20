"use client";

import { useEffect, useState } from "react";

import { getRuntimeEvents, getRuntimeSnapshot, runtimeWsUrl } from "@/lib/runtime/client";
import { type GraphState, type StreamFrame, initialGraphState, reduce } from "@/lib/stream/reducer";

/**
 * Mirrors useExperimentStream, deliberately rather than generalizing it.
 *
 * The frame protocol and the pure `reduce()` are shared verbatim, so the /demo
 * screen gets the same snapshot-then-deltas semantics and the same treatment
 * of a `seq` gap as a fatal desync (SPEC §4) for free. What is *not* shared is
 * ExperimentProvider: the live session is a peer of the simulator's run, not a
 * mode of it, and the simulator's provider and sessionStorage key stay
 * untouched (docs/ARCHITECTURE.md §7.4).
 *
 * One thing it does that the simulator's hook does not: **backfill**. A live
 * session is created by a WorkSwarm run that may already be finished by the
 * time anyone opens /demo, and the socket's snapshot carries node state but no
 * history — so a run that actually detected an attack would show an empty
 * timeline and four unlit verdict lights. Attaching therefore reads the
 * snapshot and the replay buffer over HTTP first, then opens the socket from
 * `snapshot.last_seq`, which the ring buffer covers with no gap.
 */

const MIN_BACKOFF_MS = 250;
const MAX_BACKOFF_MS = 5000;

export type RuntimeStream = {
  state: GraphState;
  schemaError: string | null;
  connected: boolean;
};

export function useRuntimeStream(sessionId: string | null): RuntimeStream {
  const [state, setState] = useState<GraphState>(initialGraphState);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    // No session to attach to yet. Any state left from a previous session is
    // not cleared here: `reduce()` already resets everything when a snapshot
    // arrives for a different session id, and callers scope what they read to
    // `state.experimentId` so a stale frame can never be shown as current.
    if (!sessionId) return;
    const id = sessionId;

    let socket: WebSocket | null = null;
    let cancelled = false;
    let backoff = MIN_BACKOFF_MS;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    const controller = new AbortController();
    // The next seq we expect, from either the last snapshot's last_seq or the
    // last event frame actually applied. A gap here is a fatal desync.
    let expectedNextSeq: number | null = null;

    function apply(frame: StreamFrame): boolean {
      try {
        setState((prev) => reduce(prev, frame));
        expectedNextSeq = frame.type === "snapshot" ? frame.last_seq + 1 : frame.event.seq + 1;
        setSchemaError(null);
        return true;
      } catch (err) {
        setSchemaError(err instanceof Error ? err.message : String(err));
        return false;
      }
    }

    function scheduleReconnect(sinceSeq: number | undefined) {
      if (cancelled) return;
      reconnectTimer = setTimeout(() => {
        backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
        connect(sinceSeq);
      }, backoff);
    }

    function connect(sinceSeq?: number) {
      if (cancelled) return;
      socket = new WebSocket(runtimeWsUrl(id, sinceSeq));

      socket.onopen = () => {
        backoff = MIN_BACKOFF_MS;
        setConnected(true);
      };

      socket.onmessage = (ev: MessageEvent<string>) => {
        const frame = JSON.parse(ev.data) as StreamFrame;

        if (
          frame.type === "event" &&
          expectedNextSeq !== null &&
          frame.event.seq !== expectedNextSeq
        ) {
          socket?.close();
          scheduleReconnect(undefined); // force a fresh snapshot
          return;
        }

        if (!apply(frame)) {
          socket?.close();
        }
      };

      socket.onclose = () => {
        setConnected(false);
        if (cancelled) return;
        scheduleReconnect(expectedNextSeq !== null ? expectedNextSeq - 1 : undefined);
      };

      socket.onerror = () => {
        socket?.close();
      };
    }

    async function attach() {
      try {
        const snapshot = await getRuntimeSnapshot(id, controller.signal);
        if (cancelled) return;
        if (!apply(snapshot)) return;

        const page = await getRuntimeEvents(id, -1, controller.signal);
        if (cancelled) return;
        for (const event of page.events) {
          // Replaying history over the snapshot is idempotent: the reducer's
          // node mutations set the same terminal state the snapshot already
          // has, and this is what fills the timeline and the verdict strip.
          if (!apply({ type: "event", event })) return;
        }

        connect(snapshot.last_seq);
      } catch {
        if (cancelled) return;
        // Backfill is an optimization, not a requirement: fall back to the
        // socket's own snapshot rather than leaving the screen blank.
        connect();
      }
    }

    void attach();

    return () => {
      cancelled = true;
      controller.abort();
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [sessionId]);

  return { state, schemaError, connected };
}
