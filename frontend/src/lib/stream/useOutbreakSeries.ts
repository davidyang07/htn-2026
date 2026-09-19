"use client";

import { useEffect, useRef, useState } from "react";

import { selectMetrics, type GraphState } from "@/lib/stream/reducer";

export type OutbreakSample = {
  tick: number;
  healthy: number;
  compromised: number;
  quarantined: number;
  total: number;
};

// One sample per simulated tick; a 2000-tick run is the documented ceiling,
// so the series is bounded without needing a ring buffer.
const MAX_SAMPLES = 2000;

/**
 * Samples the fleet's security-state split once per simulated tick.
 *
 * The backend exposes only the *current* state, so an outbreak curve has to be
 * accumulated client-side from the stream the dashboard is already consuming —
 * no new endpoint, no extra requests.
 */
export function useOutbreakSeries(state: GraphState): OutbreakSample[] {
  const [series, setSeries] = useState<OutbreakSample[]>([]);
  const lastTick = useRef(-1);
  const experimentId = useRef<string | null>(null);

  useEffect(() => {
    if (state.experimentId !== experimentId.current) {
      experimentId.current = state.experimentId;
      lastTick.current = -1;
      setSeries([]);
      return;
    }
    if (state.nodes.size === 0) return;
    // Ticks can also move backwards, when a replay is scrubbed — rebuild from
    // that point rather than appending an out-of-order sample.
    if (state.tick === lastTick.current) return;
    const metrics = selectMetrics(state);
    const sample: OutbreakSample = {
      tick: state.tick,
      healthy: metrics.healthy,
      compromised: metrics.compromised,
      quarantined: metrics.quarantined,
      total: metrics.total,
    };
    const rewound = state.tick < lastTick.current;
    lastTick.current = state.tick;
    setSeries((prev) => {
      const base = rewound ? prev.filter((s) => s.tick < sample.tick) : prev;
      return [...base, sample].slice(-MAX_SAMPLES);
    });
  }, [state]);

  return series;
}
