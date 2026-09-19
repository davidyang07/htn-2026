"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  createExperiment,
  getExperiment,
  pauseExperiment,
  resumeExperiment,
  setSpeed,
  stopExperiment,
  type ExperimentConfig,
} from "@/lib/api/client";
import {
  canPause,
  canReset,
  canResume,
  canSetSpeed,
  canStart,
  controlReducer,
  initialControlState,
  type ControlAction,
  type ControlState,
} from "@/lib/controls/reducer";
import { initialGraphState, type GraphState } from "@/lib/stream/reducer";
import { useExperimentStream } from "@/lib/stream/useExperimentStream";

// While a run is "running", the WS stream never surfaces a status change on
// its own (SnapshotFrame.status is sent only once, on connect/reconnect;
// EventFrame carries no status field) — so natural completion (reaching
// max_ticks, or full containment) is otherwise invisible to a connected
// client. Poll GET /{id} to close that gap (docs/M1_F5_PLAN.md §4).
const STATUS_POLL_INTERVAL_MS = 1000;

// The workspace is a multi-route shell, so the active run has to survive a
// reload as well as navigation between screens. Only the id is stored; status
// and config are re-fetched, keeping the backend the sole authority.
const ACTIVE_RUN_KEY = "agentshield.activeExperimentId";

type ControlApi = {
  control: ControlState;
  /** True while a run id adopted from a previous page load is being verified. */
  hydrating: boolean;
  canStart: boolean;
  canPause: boolean;
  canResume: boolean;
  canReset: boolean;
  canSetSpeed: boolean;
  start: (config: ExperimentConfig) => void;
  pause: () => void;
  resume: () => void;
  reset: () => void;
  changeSpeed: (multiplier: number) => void;
};

export type ExperimentContextValue = ControlApi & {
  /** GraphState folded from the live WS stream for the active run. */
  stream: GraphState;
  schemaError: string | null;
};

const ControlContext = createContext<ControlApi | null>(null);
const StreamContext = createContext<{ stream: GraphState; schemaError: string | null }>({
  stream: initialGraphState,
  schemaError: null,
});
const ExperimentContext = createContext<ExperimentContextValue | null>(null);

/**
 * Owns the live stream for one experiment id. Mounted with `key={experimentId}`
 * so a new run resets stream state for free — the same remount-by-key
 * convention the previous single-page view used, lifted into the shell so the
 * connection now survives navigation between workspace screens.
 */
function StreamHost({
  experimentId,
  children,
}: {
  experimentId: string | null;
  children: ReactNode;
}) {
  const { state, schemaError } = useExperimentStream(experimentId);
  const value = useMemo(() => ({ stream: state, schemaError }), [state, schemaError]);
  return <StreamContext.Provider value={value}>{children}</StreamContext.Provider>;
}

/** Joins the two halves so consumers see one flat context object. Separate
 * providers underneath keep a stream frame from re-running every control
 * memo, and vice versa. */
function ExperimentBridge({ children }: { children: ReactNode }) {
  const control = useContext(ControlContext);
  const stream = useContext(StreamContext);
  if (!control) throw new Error("ExperimentBridge used outside ExperimentProvider");
  const value = useMemo<ExperimentContextValue>(
    () => ({ ...control, stream: stream.stream, schemaError: stream.schemaError }),
    [control, stream],
  );
  return <ExperimentContext.Provider value={value}>{children}</ExperimentContext.Provider>;
}

export function ExperimentProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(controlReducer, initialControlState);
  const [hydrating, setHydrating] = useState(true);
  const stateRef = useRef(state);
  const nextOperationId = useRef(1);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const apply = useCallback((action: ControlAction) => {
    const next = controlReducer(stateRef.current, action);
    if (next === stateRef.current) return false;
    stateRef.current = next;
    dispatch(action);
    return true;
  }, []);

  // Re-adopt the run this tab was watching before a reload. The backend is
  // asked to confirm it still exists; a 404 (evicted) or any other failure
  // drops it and lands on the launch screen rather than showing a dead run.
  useEffect(() => {
    let cancelled = false;
    const stored =
      typeof window === "undefined" ? null : window.sessionStorage.getItem(ACTIVE_RUN_KEY);
    // Every setState below lives in a resolution callback, never synchronously
    // in the effect body — the "nothing stored" case resolves through an
    // already-settled promise for exactly that reason.
    const adopt = stored ? getExperiment(stored) : Promise.resolve(null);
    adopt
      .then((summary) => {
        if (cancelled || summary === null) return;
        const operationId = nextOperationId.current++;
        apply({ type: "start_requested", operationId });
        apply({
          type: "start_succeeded",
          operationId,
          experimentId: summary.experiment_id,
          status: summary.status,
          config: summary.config,
        });
      })
      .catch(() => {
        // The stored run is gone (evicted, or the backend restarted) — drop it
        // and land on the launch screen rather than showing a dead run.
        if (typeof window !== "undefined") window.sessionStorage.removeItem(ACTIVE_RUN_KEY);
      })
      .finally(() => {
        if (!cancelled) setHydrating(false);
      });
    return () => {
      cancelled = true;
    };
  }, [apply]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (state.experimentId) window.sessionStorage.setItem(ACTIVE_RUN_KEY, state.experimentId);
  }, [state.experimentId]);

  const start = useCallback(
    (config: ExperimentConfig) => {
      if (!canStart(stateRef.current)) return;
      const operationId = nextOperationId.current++;
      if (!apply({ type: "start_requested", operationId })) return;
      createExperiment(config)
        .then((summary) => {
          apply({
            type: "start_succeeded",
            operationId,
            experimentId: summary.experiment_id,
            status: summary.status,
            config: summary.config,
          });
        })
        .catch((err) => {
          apply({
            type: "start_failed",
            operationId,
            error: err instanceof Error ? err.message : String(err),
          });
        });
    },
    [apply],
  );

  const pause = useCallback(() => {
    if (!canPause(stateRef.current) || !stateRef.current.experimentId) return;
    const id = stateRef.current.experimentId;
    const operationId = nextOperationId.current++;
    if (!apply({ type: "pause_requested", operationId })) return;
    pauseExperiment(id)
      .then((summary) => apply({ type: "pause_succeeded", operationId, status: summary.status }))
      .catch((err) => {
        apply({
          type: "pause_failed",
          operationId,
          error: err instanceof Error ? err.message : String(err),
        });
      });
  }, [apply]);

  const resume = useCallback(() => {
    if (!canResume(stateRef.current) || !stateRef.current.experimentId) return;
    const id = stateRef.current.experimentId;
    const operationId = nextOperationId.current++;
    if (!apply({ type: "resume_requested", operationId })) return;
    resumeExperiment(id)
      .then((summary) => apply({ type: "resume_succeeded", operationId, status: summary.status }))
      .catch((err) => {
        apply({
          type: "resume_failed",
          operationId,
          error: err instanceof Error ? err.message : String(err),
        });
      });
  }, [apply]);

  const changeSpeed = useCallback(
    (multiplier: number) => {
      if (!canSetSpeed(stateRef.current) || !stateRef.current.experimentId) return;
      const id = stateRef.current.experimentId;
      const operationId = nextOperationId.current++;
      if (!apply({ type: "speed_requested", operationId })) return;
      setSpeed(id, multiplier)
        .then(() => apply({ type: "speed_succeeded", operationId, speed: multiplier }))
        .catch((err) => {
          apply({
            type: "speed_failed",
            operationId,
            error: err instanceof Error ? err.message : String(err),
          });
        });
    },
    [apply],
  );

  // Reset ordering (docs/M1_F5_PLAN.md §5): await stopping the old
  // experiment (idempotent / 404-tolerant — either way it's gone), only
  // then create the new one, and only then swap the active experimentId/
  // status — so there is never a moment with two experiments simultaneously
  // active in local state, and a create failure after a successful stop is
  // reported as "stopped", not silently left pointing at a dead run.
  const reset = useCallback(async () => {
    if (!canReset(stateRef.current) || !stateRef.current.experimentId) return;
    const oldId = stateRef.current.experimentId;
    const configToRerun = stateRef.current.activeConfig;
    if (!configToRerun) return;
    const operationId = nextOperationId.current++;
    if (!apply({ type: "reset_requested", operationId })) return;

    try {
      await stopExperiment(oldId);
    } catch (err) {
      // A 404 means the old experiment is already gone (evicted) — that's
      // the desired end state, not a failure, so fall through to create.
      // Anything else means the old run's stop status is unknown: abort
      // without touching state, so it's cleanly retryable.
      if (!(err instanceof Error && err.message.includes("404"))) {
        apply({
          type: "reset_failed",
          operationId,
          error: err instanceof Error ? err.message : String(err),
        });
        return;
      }
    }

    // The old run is now confirmed stopped-or-gone. A failure from here on
    // must not leave local state claiming the old run is still "running".
    try {
      const summary = await createExperiment(configToRerun);
      apply({
        type: "reset_create_succeeded",
        operationId,
        experimentId: summary.experiment_id,
        status: summary.status,
        config: summary.config,
      });
    } catch (err) {
      apply({
        type: "reset_stop_succeeded_create_failed",
        operationId,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }, [apply]);

  // Closes the REST/WS status gap for natural completion (docs/M1_F5_PLAN.md §4).
  useEffect(() => {
    if (state.status !== "running" || state.pending !== null || !state.experimentId) return;
    const id = state.experimentId;
    const revision = state.revision;
    const controller = new AbortController();
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = () => {
      getExperiment(id, controller.signal)
        .then((summary) =>
          apply({ type: "status_synced", experimentId: id, revision, status: summary.status }),
        )
        .catch(() => {
          // Transient network hiccup — next tick retries. A genuine 404
          // (evicted out from under us) is left for the user's next
          // control action to surface, rather than guessing here.
        })
        .finally(() => {
          if (!cancelled) timer = setTimeout(poll, STATUS_POLL_INTERVAL_MS);
        });
    };
    timer = setTimeout(poll, STATUS_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [apply, state.status, state.pending, state.experimentId, state.revision]);

  const runReset = useCallback(() => {
    void reset();
  }, [reset]);

  const controlValue = useMemo<ControlApi>(
    () => ({
      control: state,
      hydrating,
      canStart: canStart(state),
      canPause: canPause(state),
      canResume: canResume(state),
      canReset: canReset(state),
      canSetSpeed: canSetSpeed(state),
      start,
      pause,
      resume,
      reset: runReset,
      changeSpeed,
    }),
    [state, hydrating, start, pause, resume, runReset, changeSpeed],
  );

  return (
    <ControlContext.Provider value={controlValue}>
      <StreamHost key={state.experimentId ?? "no-run"} experimentId={state.experimentId}>
        <ExperimentBridge>{children}</ExperimentBridge>
      </StreamHost>
    </ControlContext.Provider>
  );
}

export function useExperiment(): ExperimentContextValue {
  const value = useContext(ExperimentContext);
  if (!value) throw new Error("useExperiment must be used inside an ExperimentProvider");
  return value;
}
