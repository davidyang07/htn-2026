"use client";

import { useEffect, useRef, useState } from "react";

import { type GraphState, type Event, initialGraphState, reduce } from "@/lib/stream/reducer";

import { foldEvents, loadReplayData } from "./loadReplayData";

// Matches ExperimentRunner.tick_interval_default -- purely for UI-pacing
// consistency with the live view's cadence at speed=1, even though the
// clamp is cosmetic in a client-only, network-free replay.
const BASE_TICK_INTERVAL_MS = 250;
const MIN_SPEED = 0.25;
const MAX_SPEED = 8.0;

export type ReplayStreamResult = {
  state: GraphState;
  loading: boolean;
  /** Events fetched so far — a long run's log takes several paged requests,
   * and an indefinite spinner reads as a hang. */
  loadedEvents: number;
  error: string | null;
  incomplete: boolean;
  totalEvents: number;
  playedCount: number;
  seek: (index: number) => void;
};

/**
 * Thin React wrapper around loadReplayData: owns loading/playback state and
 * an interval-driven scheduler that advances one event at a time through
 * reduce() while playing. No further network calls after the initial fetch
 * -- pause/resume/speed/seek are all local.
 *
 * Like ExperimentView/useExperimentStream, this hook does not reset its own
 * state reactively when `experimentId` changes -- the caller must key its
 * component by experimentId so a different replay target remounts fresh
 * (see app/page.tsx's `key={state.experimentId}` for the live-view
 * precedent this mirrors).
 */
export function useReplayStream(
  experimentId: string | null,
  speed: number,
  playing: boolean,
): ReplayStreamResult {
  const [state, setState] = useState<GraphState>(initialGraphState);
  const [loading, setLoading] = useState(true);
  const [loadedEvents, setLoadedEvents] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [incomplete, setIncomplete] = useState(false);
  const [playedCount, setPlayedCount] = useState(0);
  const [totalEvents, setTotalEvents] = useState(0);

  const snapshotStateRef = useRef<GraphState>(initialGraphState);
  const eventsRef = useRef<Event[]>([]);
  const playedIndexRef = useRef(0);

  useEffect(() => {
    if (!experimentId) return;
    let cancelled = false;

    loadReplayData(experimentId, (loaded) => {
      if (!cancelled) setLoadedEvents(loaded);
    }).then(
      (data) => {
        if (cancelled) return;
        snapshotStateRef.current = data.initialState;
        eventsRef.current = data.events;
        setIncomplete(data.incomplete);
        setTotalEvents(data.events.length);
        setState(data.initialState);
        setLoading(false);
      },
      (err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      },
    );

    return () => {
      cancelled = true;
    };
  }, [experimentId]);

  useEffect(() => {
    if (!playing || loading || error) return;
    const clampedSpeed = Math.min(MAX_SPEED, Math.max(MIN_SPEED, speed));
    const intervalMs = BASE_TICK_INTERVAL_MS / clampedSpeed;

    const timer = setInterval(() => {
      const events = eventsRef.current;
      const idx = playedIndexRef.current;
      if (idx >= events.length) {
        clearInterval(timer);
        return;
      }
      const event = events[idx];
      setState((prev) => reduce(prev, { type: "event", event }));
      playedIndexRef.current = idx + 1;
      setPlayedCount(idx + 1);
    }, intervalMs);

    return () => clearInterval(timer);
  }, [playing, speed, loading, error]);

  function seek(index: number) {
    const events = eventsRef.current;
    const clamped = Math.max(0, Math.min(index, events.length));
    const next = foldEvents(snapshotStateRef.current, events, clamped);
    playedIndexRef.current = clamped;
    setPlayedCount(clamped);
    setState(next);
  }

  return { state, loading, loadedEvents, error, incomplete, totalEvents, playedCount, seek };
}
