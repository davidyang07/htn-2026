"use client";

import { useEffect, useState } from "react";

import { backendWsUrl } from "@/lib/api/client";
import { type GraphState, type StreamFrame, initialGraphState, reduce } from "@/lib/stream/reducer";

const MIN_BACKOFF_MS = 250;
const MAX_BACKOFF_MS = 5000;

export function useExperimentStream(experimentId: string | null): {
  state: GraphState;
  schemaError: string | null;
} {
  const [state, setState] = useState<GraphState>(initialGraphState);
  const [schemaError, setSchemaError] = useState<string | null>(null);

  useEffect(() => {
    if (!experimentId) return;

    let socket: WebSocket | null = null;
    let cancelled = false;
    let backoff = MIN_BACKOFF_MS;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    // Tracks the next seq we expect, from either the last snapshot's
    // last_seq or the last event frame actually applied — a gap here is a
    // fatal desync per SPEC §4.
    let expectedNextSeq: number | null = null;

    function scheduleReconnect(sinceSeq: number | undefined) {
      if (cancelled) return;
      reconnectTimer = setTimeout(() => {
        backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
        connect(sinceSeq);
      }, backoff);
    }

    function connect(sinceSeq?: number) {
      if (cancelled || !experimentId) return;
      socket = new WebSocket(backendWsUrl(experimentId, sinceSeq));

      socket.onopen = () => {
        backoff = MIN_BACKOFF_MS;
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

        try {
          setState((prev) => reduce(prev, frame));
          expectedNextSeq = frame.type === "snapshot" ? frame.last_seq + 1 : frame.event.seq + 1;
          setSchemaError(null);
        } catch (err) {
          setSchemaError(err instanceof Error ? err.message : String(err));
          socket?.close();
        }
      };

      socket.onclose = () => {
        if (cancelled) return;
        scheduleReconnect(expectedNextSeq !== null ? expectedNextSeq - 1 : undefined);
      };

      socket.onerror = () => {
        socket?.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [experimentId]);

  return { state, schemaError };
}
