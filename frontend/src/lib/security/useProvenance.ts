"use client";

import { useEffect, useState } from "react";

import { getProvenance, getReplayProvenance } from "@/lib/api/client";

import type { InsightsMode } from "./useSecurityInsights";

export type ProvenanceState = {
  chain: string[] | null;
  loading: boolean;
  error: string | null;
};

/**
 * The causal trace for one node, fetched whenever the selection changes.
 *
 * Previously this was a text input the operator had to type a node id into.
 * Selecting a node in the graph *is* the question "how did this happen", so
 * the answer is fetched on selection instead of on demand.
 */
export function useProvenance(
  experimentId: string | null,
  nodeId: string | null,
  mode: InsightsMode = "live",
): ProvenanceState {
  const [state, setState] = useState<ProvenanceState>({
    chain: null,
    loading: false,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    // Resolved through a promise even when there is nothing to fetch, so every
    // setState stays inside a resolution callback rather than running
    // synchronously in the effect body.
    const request =
      !experimentId || !nodeId
        ? Promise.resolve(null)
        : mode === "live"
          ? getProvenance(experimentId, nodeId)
          : getReplayProvenance(experimentId, nodeId);
    request.then(
      (response) => {
        if (!cancelled) setState({ chain: response?.chain ?? null, loading: false, error: null });
      },
      (err: unknown) => {
        if (cancelled) return;
        setState({
          chain: null,
          loading: false,
          // A non-agent node has no compromise chain to trace; the endpoint
          // 404s for it, which is an answer rather than a failure.
          error: err instanceof Error ? err.message : String(err),
        });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [experimentId, nodeId, mode]);

  return state;
}
