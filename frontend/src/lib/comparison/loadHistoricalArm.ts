import { getExperimentDetail, getReplayMetrics, type MetricsResponse } from "@/lib/api/client";

export type HistoricalArmResult = {
  experimentId: string;
  metrics: MetricsResponse;
  incomplete: boolean;
};

/**
 * Direct sibling of runToCompletion.ts for a *historical* arm: fetches the
 * same rich MetricsResponse a live arm now fetches (docs/PLAN.md §9's "Next
 * recommended milestone"), via the /replay/metrics endpoint added in
 * app/api/routes_history.py -- no client-side event-log fold needed, since
 * that endpoint already reconstructs the persisted run's final state
 * server-side (app/engine/replay.py). `incomplete` is read directly from
 * the experiment's `is_complete` column (the exact same source
 * loadReplayData's own `incomplete` flag already used).
 */
export async function loadHistoricalArm(experimentId: string): Promise<HistoricalArmResult> {
  const [metrics, detail] = await Promise.all([
    getReplayMetrics(experimentId),
    getExperimentDetail(experimentId),
  ]);
  return { experimentId, metrics, incomplete: detail.is_complete !== true };
}
