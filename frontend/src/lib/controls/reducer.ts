// Pure control-lifecycle state, mirroring the F3 backend's own transition
// table (docs/M1_F3_PLAN.md §3) client-side for UX responsiveness. The
// backend remains sole authority (BRIEF §6) — this reducer only decides
// what the UI shows and which actions it lets a user attempt; it never
// simulates tick/pause behavior itself (docs/M1_F5_PLAN.md §4/§6).
//
// No React/DOM dependency, so it's unit-testable directly, same discipline
// as lib/stream/reducer.ts.

import type { ExperimentConfig } from "@/lib/api/client";

export type ControlStatus = "idle" | "running" | "paused" | "finished" | "stopped";
export type PendingAction = "start" | "pause" | "resume" | "speed" | "reset" | null;

export type ControlState = {
  experimentId: string | null;
  status: ControlStatus;
  pending: PendingAction;
  speed: number;
  error: string | null;
  operationId: number | null;
  revision: number;
  activeConfig: ExperimentConfig | null;
};

export const initialControlState: ControlState = {
  experimentId: null,
  status: "idle",
  pending: null,
  speed: 1,
  error: null,
  operationId: null,
  revision: 0,
  activeConfig: null,
};

export function canStart(s: ControlState): boolean {
  // "idle" (never run yet) plus the two terminal statuses ("finished",
  // "stopped") — a run that has ended, one way or another, has no live
  // background task, so starting a brand-new experiment from here is safe.
  // Excluding "running"/"paused" is what forces Reset (which stops the old
  // run first) rather than Start to be used while a run is still active.
  // Without the terminal statuses here, the config form would permanently
  // lock up after the very first Start for the rest of the session — Reset
  // only ever reruns the *same* activeConfig, so this is the only way to
  // launch a second, differently-configured experiment without a refresh.
  return (
    (s.status === "idle" || s.status === "finished" || s.status === "stopped") &&
    s.pending === null
  );
}

export function canPause(s: ControlState): boolean {
  return s.status === "running" && s.pending === null;
}

export function canResume(s: ControlState): boolean {
  return s.status === "paused" && s.pending === null;
}

export function canSetSpeed(s: ControlState): boolean {
  return (s.status === "running" || s.status === "paused") && s.pending === null;
}

export function canReset(s: ControlState): boolean {
  return s.experimentId !== null && s.pending === null;
}

export type ControlAction =
  | { type: "start_requested"; operationId: number }
  | { type: "start_succeeded"; operationId: number; experimentId: string; status: ControlStatus; config: ExperimentConfig }
  | { type: "start_failed"; operationId: number; error: string }
  | { type: "pause_requested"; operationId: number }
  | { type: "pause_succeeded"; operationId: number; status: ControlStatus }
  | { type: "pause_failed"; operationId: number; error: string }
  | { type: "resume_requested"; operationId: number }
  | { type: "resume_succeeded"; operationId: number; status: ControlStatus }
  | { type: "resume_failed"; operationId: number; error: string }
  | { type: "speed_requested"; operationId: number }
  | { type: "speed_succeeded"; operationId: number; speed: number }
  | { type: "speed_failed"; operationId: number; error: string }
  | { type: "reset_requested"; operationId: number }
  | { type: "reset_create_succeeded"; operationId: number; experimentId: string; status: ControlStatus; config: ExperimentConfig }
  | { type: "reset_stop_succeeded_create_failed"; operationId: number; error: string }
  | { type: "reset_failed"; operationId: number; error: string }
  | { type: "status_synced"; experimentId: string; revision: number; status: ControlStatus };

function isCurrent(state: ControlState, pending: Exclude<PendingAction, null>, operationId: number) {
  return state.pending === pending && state.operationId === operationId;
}

export function controlReducer(state: ControlState, action: ControlAction): ControlState {
  switch (action.type) {
    case "start_requested":
      if (!canStart(state)) return state;
      return { ...state, pending: "start", operationId: action.operationId, revision: state.revision + 1, error: null };
    case "start_succeeded":
      if (!isCurrent(state, "start", action.operationId)) return state;
      return {
        ...state,
        experimentId: action.experimentId,
        status: action.status,
        pending: null,
        operationId: null,
        // A fresh backend runner always starts at its own default speed
        // (1.0), regardless of what the previous run's speed happened to
        // be left at — matters once Start can fire again after a prior run
        // ended (canStart above), not just on the very first Start.
        speed: 1,
        error: null,
        activeConfig: action.config,
      };
    case "start_failed":
      if (!isCurrent(state, "start", action.operationId)) return state;
      return { ...state, pending: null, operationId: null, error: action.error };

    case "pause_requested":
      if (!canPause(state)) return state;
      return { ...state, pending: "pause", operationId: action.operationId, revision: state.revision + 1, error: null };
    case "pause_succeeded":
      if (!isCurrent(state, "pause", action.operationId)) return state;
      return { ...state, status: action.status, pending: null, operationId: null, error: null };
    case "pause_failed":
      if (!isCurrent(state, "pause", action.operationId)) return state;
      return { ...state, pending: null, operationId: null, error: action.error };

    case "resume_requested":
      if (!canResume(state)) return state;
      return { ...state, pending: "resume", operationId: action.operationId, revision: state.revision + 1, error: null };
    case "resume_succeeded":
      if (!isCurrent(state, "resume", action.operationId)) return state;
      return { ...state, status: action.status, pending: null, operationId: null, error: null };
    case "resume_failed":
      if (!isCurrent(state, "resume", action.operationId)) return state;
      return { ...state, pending: null, operationId: null, error: action.error };

    case "speed_requested":
      if (!canSetSpeed(state)) return state;
      return { ...state, pending: "speed", operationId: action.operationId, revision: state.revision + 1, error: null };
    case "speed_succeeded":
      if (!isCurrent(state, "speed", action.operationId)) return state;
      return { ...state, speed: action.speed, pending: null, operationId: null, error: null };
    case "speed_failed":
      if (!isCurrent(state, "speed", action.operationId)) return state;
      return { ...state, pending: null, operationId: null, error: action.error };

    case "reset_requested":
      if (!canReset(state)) return state;
      return { ...state, pending: "reset", operationId: action.operationId, revision: state.revision + 1, error: null };
    case "reset_create_succeeded":
      if (!isCurrent(state, "reset", action.operationId)) return state;
      return {
        ...state,
        experimentId: action.experimentId,
        status: action.status,
        pending: null,
        operationId: null,
        speed: 1,
        error: null,
        activeConfig: action.config,
      };
    case "reset_stop_succeeded_create_failed":
      if (!isCurrent(state, "reset", action.operationId)) return state;
      return { ...state, status: "stopped", pending: null, operationId: null, error: action.error };
    case "reset_failed":
      if (!isCurrent(state, "reset", action.operationId)) return state;
      return { ...state, pending: null, operationId: null, error: action.error };

    case "status_synced":
      if (action.experimentId !== state.experimentId || action.revision !== state.revision) return state;
      return { ...state, status: action.status };

    default:
      return state;
  }
}
