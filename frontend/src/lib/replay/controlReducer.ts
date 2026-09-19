// Replay's own small control-state reducer -- deliberately separate from
// lib/controls/reducer.ts, whose entire design mirrors the backend's REST
// transition table and assumes every action costs a network round-trip.
// Replay's pause/resume/speed are synchronous and network-free (the whole
// point of driving reduce() from a prefetched log), so bolting them onto
// that state machine would force every existing handler there to
// special-case "is this actually going to hit the network"
// (docs/PHASE_1_5_PLAN.md §7).

const MIN_SPEED = 0.25;
const MAX_SPEED = 8.0;

export type ReplayControlState = {
  playing: boolean;
  speed: number;
};

export const initialReplayControlState: ReplayControlState = {
  playing: false,
  speed: 1,
};

export type ReplayControlAction =
  | { type: "play" }
  | { type: "pause" }
  | { type: "toggle_play" }
  | { type: "set_speed"; speed: number }
  | { type: "reset" };

export function replayControlReducer(
  state: ReplayControlState,
  action: ReplayControlAction,
): ReplayControlState {
  switch (action.type) {
    case "play":
      return { ...state, playing: true };
    case "pause":
      return { ...state, playing: false };
    case "toggle_play":
      return { ...state, playing: !state.playing };
    case "set_speed":
      return { ...state, speed: Math.min(MAX_SPEED, Math.max(MIN_SPEED, action.speed)) };
    case "reset":
      return initialReplayControlState;
    default:
      return state;
  }
}
