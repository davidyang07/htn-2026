"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getBlastRadius,
  getCriticalNodes,
  getMetrics,
  getRemediation,
  getReplayBlastRadius,
  getReplayCriticalNodes,
  getReplayMetrics,
  getReplayRemediation,
  getReplaySecurityGraph,
  getSecurityGraph,
  type BlastRadiusResponse,
  type CriticalNodeView,
  type MetricsResponse,
  type RemediationResponse,
  type SecurityGraphView,
} from "@/lib/api/client";

// The security graph, metrics, analysis and remediation endpoints are
// computed-on-demand REST resources with no push channel, so they are polled
// — the same pattern the live view already uses to close the status gap.
const POLL_INTERVAL_MS = 2000;

const CRITICAL_NODE_COUNT = 6;

export type InsightsMode = "live" | "replay";

export type SecurityInsights = {
  metrics: MetricsResponse | null;
  graph: SecurityGraphView | null;
  criticalNodes: CriticalNodeView[];
  blastRadius: BlastRadiusResponse | null;
  remediation: RemediationResponse | null;
  /** True until the first successful load; false forever after, so a poll
   * failure mid-run shows an error next to stale data rather than wiping the
   * screen back to a spinner. */
  loading: boolean;
  error: string | null;
};

const EMPTY: SecurityInsights = {
  metrics: null,
  graph: null,
  criticalNodes: [],
  blastRadius: null,
  remediation: null,
  loading: true,
  error: null,
};

/**
 * Loads every derived security resource for one experiment. A replayed run's
 * reconstructed state is static, so it is fetched exactly once; a live run is
 * polled until unmount.
 */
export function useSecurityInsights(
  experimentId: string | null,
  mode: InsightsMode = "live",
): SecurityInsights {
  const [insights, setInsights] = useState<SecurityInsights>(EMPTY);

  const fetchAll = useCallback(
    (id: string) =>
      mode === "live"
        ? Promise.all([
            getMetrics(id),
            getSecurityGraph(id),
            getCriticalNodes(id, CRITICAL_NODE_COUNT),
            getRemediation(id),
            getBlastRadius(id),
          ])
        : Promise.all([
            getReplayMetrics(id),
            getReplaySecurityGraph(id),
            getReplayCriticalNodes(id, CRITICAL_NODE_COUNT),
            getReplayRemediation(id),
            getReplayBlastRadius(id),
          ]),
    [mode],
  );

  useEffect(() => {
    if (!experimentId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const poll = () => {
      fetchAll(experimentId)
        .then(([metrics, graph, critical, remediation, blastRadius]) => {
          if (cancelled) return;
          setInsights({
            metrics,
            graph,
            criticalNodes: critical.nodes,
            blastRadius,
            remediation,
            loading: false,
            error: null,
          });
        })
        .catch((err) => {
          if (cancelled) return;
          setInsights((prev) => ({
            ...prev,
            loading: false,
            error: err instanceof Error ? err.message : String(err),
          }));
        })
        .finally(() => {
          if (!cancelled && mode === "live") timer = setTimeout(poll, POLL_INTERVAL_MS);
        });
    };
    poll();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [experimentId, mode, fetchAll]);

  return experimentId ? insights : EMPTY;
}
