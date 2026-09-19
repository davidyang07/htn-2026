"use client";

import { useCallback, useRef, useState } from "react";

import type { ExperimentConfig, MetricsResponse } from "@/lib/api/client";
import { runExperimentToCompletion } from "@/lib/comparison/runToCompletion";

export type TrialArm =
  | { status: "idle" }
  | { status: "running" }
  | { status: "done"; metrics: MetricsResponse; experimentId: string }
  | { status: "error"; error: string };

export type FixTrial = {
  /** The recommendation being validated, keyed by its config diff. */
  diffKey: string | null;
  before: TrialArm;
  after: TrialArm;
  running: boolean;
  /** Runs the baseline config and the remediated config to completion. */
  validate: (baseConfig: ExperimentConfig, configDiff: Record<string, unknown>) => void;
};

const IDLE: TrialArm = { status: "idle" };

/**
 * The "re-test" half of Remediate → Re-test.
 *
 * A recommendation's `config_diff` is directly usable as a `POST /api/experiments`
 * body, so validating a fix needs no new machinery: run the baseline config and
 * the patched config to completion and compare the same metrics. Previously the
 * UI displayed the diff and left the operator to reproduce it by hand.
 */
export function useFixTrial(): FixTrial {
  const [diffKey, setDiffKey] = useState<string | null>(null);
  const [before, setBefore] = useState<TrialArm>(IDLE);
  const [after, setAfter] = useState<TrialArm>(IDLE);
  // A ref, not state: a second click can arrive before the state update that
  // would have blocked it has re-rendered.
  const runningRef = useRef(false);
  const [running, setRunning] = useState(false);

  const validate = useCallback(
    (baseConfig: ExperimentConfig, configDiff: Record<string, unknown>) => {
      if (runningRef.current) return;
      runningRef.current = true;
      setRunning(true);
      setDiffKey(JSON.stringify(configDiff));
      setBefore({ status: "running" });
      setAfter({ status: "running" });

      const remediated = { ...baseConfig, ...configDiff } as ExperimentConfig;

      // allSettled, not all: one arm failing must not hide the other's result.
      void Promise.allSettled([
        runExperimentToCompletion(baseConfig).then(
          (result) =>
            setBefore({
              status: "done",
              metrics: result.metrics,
              experimentId: result.experimentId,
            }),
          (err) =>
            setBefore({
              status: "error",
              error: err instanceof Error ? err.message : String(err),
            }),
        ),
        runExperimentToCompletion(remediated).then(
          (result) =>
            setAfter({
              status: "done",
              metrics: result.metrics,
              experimentId: result.experimentId,
            }),
          (err) =>
            setAfter({
              status: "error",
              error: err instanceof Error ? err.message : String(err),
            }),
        ),
      ]).finally(() => {
        runningRef.current = false;
        setRunning(false);
      });
    },
    [],
  );

  return { diffKey, before, after, running, validate };
}
