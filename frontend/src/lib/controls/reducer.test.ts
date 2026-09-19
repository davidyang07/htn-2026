import { describe, expect, it } from "vitest";

import type { ExperimentConfig } from "@/lib/api/client";
import {
  canPause,
  canReset,
  canResume,
  canSetSpeed,
  canStart,
  type ControlState,
  type ControlStatus,
  controlReducer,
  initialControlState,
} from "./reducer";

const EXP_A = "11111111-1111-1111-1111-111111111111";
const EXP_B = "22222222-2222-2222-2222-222222222222";

const FIXTURE_CONFIG_A: ExperimentConfig = {
  seed: 42,
  node_count: 60,
  edge_density: 2,
  software_type_count: 3,
  p_same: 0.15,
  p_cross: 0.03,
  max_ticks: 200,
  detector_sensitivity: 0.2,
  defense_enabled: true,
  initial_compromised: "highest_degree",
  real_agent_count: 0,
  model_provider: "mock",
  model_name: "qwen-mock",
  model_max_tokens: 64,
  model_timeout_s: 20,
  model_max_retries: 1,
  model_max_concurrency: 4,
  model_max_requests_per_experiment: 500,
  tool_count: 0,
  credential_count: 0,
  resource_count: 0,
  sentinel_count: 0,
  adaptive_detection_threshold: 0.3,
  false_quarantine_rate: 0,
  sentinel_compromise_rate: 0,
  attestation_replay_rate: 0,
  byzantine_collusion_rate: 0,
};

const FIXTURE_CONFIG_B: ExperimentConfig = {
  seed: 123,
  node_count: 80,
  edge_density: 3,
  software_type_count: 4,
  p_same: 0.2,
  p_cross: 0.05,
  max_ticks: 300,
  detector_sensitivity: 0.3,
  defense_enabled: false,
  initial_compromised: "random_node",
  real_agent_count: 0,
  model_provider: "mock",
  model_name: "qwen-mock",
  model_max_tokens: 64,
  model_timeout_s: 20,
  model_max_retries: 1,
  model_max_concurrency: 4,
  model_max_requests_per_experiment: 500,
  tool_count: 0,
  credential_count: 0,
  resource_count: 0,
  sentinel_count: 0,
  adaptive_detection_threshold: 0.3,
  false_quarantine_rate: 0,
  sentinel_compromise_rate: 0,
  attestation_replay_rate: 0,
  byzantine_collusion_rate: 0,
};

function running(overrides: Partial<ControlState> = {}): ControlState {
  return {
    ...initialControlState,
    experimentId: EXP_A,
    status: "running",
    activeConfig: null,
    ...overrides,
  };
}

describe("initial state", () => {
  it("starts idle with only Start allowed", () => {
    expect(initialControlState.status).toBe("idle");
    expect(canStart(initialControlState)).toBe(true);
    expect(canPause(initialControlState)).toBe(false);
    expect(canResume(initialControlState)).toBe(false);
    expect(canSetSpeed(initialControlState)).toBe(false);
    expect(canReset(initialControlState)).toBe(false);
  });

  it("activeConfig starts as null", () => {
    expect(initialControlState.activeConfig).toBeNull();
  });
});

describe("start", () => {
  it("start_requested sets pending", () => {
    const s = controlReducer(initialControlState, { type: "start_requested", operationId: 1 });
    expect(s.pending).toBe("start");
  });

  it("a second start_requested before resolution is a no-op", () => {
    const s1 = controlReducer(initialControlState, { type: "start_requested", operationId: 1 });
    const s2 = controlReducer(s1, { type: "start_requested", operationId: 2 });
    expect(s2).toBe(s1);
  });

  it("start_requested is rejected once already running", () => {
    const s = controlReducer(running(), { type: "start_requested", operationId: 1 });
    expect(s).toEqual(running());
  });

  it("start_requested is rejected while paused", () => {
    const s = controlReducer(running({ status: "paused" }), {
      type: "start_requested",
      operationId: 1,
    });
    expect(s).toEqual(running({ status: "paused" }));
  });

  // Regression: canStart used to require status === "idle" exactly, which
  // only the very first Start of a session ever satisfies — Reset always
  // reruns the *same* activeConfig, so once a run had started there was no
  // way left to launch a *different*-configured experiment without a full
  // page refresh. A run that has ended (finished naturally, or been
  // stopped) has no live background task, so starting a brand-new
  // experiment from either state is exactly as safe as starting from idle.
  it("start_requested is accepted after a run has finished, launching a genuinely new experiment", () => {
    const finished = running({ status: "finished", activeConfig: FIXTURE_CONFIG_A });
    const s1 = controlReducer(finished, { type: "start_requested", operationId: 5 });
    expect(s1.pending).toBe("start");
    const s2 = controlReducer(s1, {
      type: "start_succeeded",
      operationId: 5,
      experimentId: EXP_B,
      status: "running",
      config: FIXTURE_CONFIG_B,
    });
    expect(s2.experimentId).toBe(EXP_B);
    expect(s2.activeConfig).toBe(FIXTURE_CONFIG_B);
    expect(s2.status).toBe("running");
  });

  it("start_requested is accepted after a run has been stopped", () => {
    const stopped = running({ status: "stopped" });
    expect(controlReducer(stopped, { type: "start_requested", operationId: 1 }).pending).toBe(
      "start",
    );
  });

  it("start_succeeded resets speed to 1, regardless of the previous run's speed", () => {
    const finished = running({ status: "finished", speed: 8 });
    const s1 = controlReducer(finished, { type: "start_requested", operationId: 1 });
    const s2 = controlReducer(s1, {
      type: "start_succeeded",
      operationId: 1,
      experimentId: EXP_B,
      status: "running",
      config: FIXTURE_CONFIG_B,
    });
    expect(s2.speed).toBe(1);
  });

  it("start_succeeded sets experimentId/status and clears pending", () => {
    const pending = controlReducer(initialControlState, { type: "start_requested", operationId: 1 });
    const s = controlReducer(pending, {
      type: "start_succeeded",
      operationId: 1,
      experimentId: EXP_A,
      status: "running",
      config: FIXTURE_CONFIG_A,
    });
    expect(s.experimentId).toBe(EXP_A);
    expect(s.status).toBe("running");
    expect(s.pending).toBeNull();
  });

  it("start_succeeded sets activeConfig from the dispatched config", () => {
    const pending = controlReducer(initialControlState, { type: "start_requested", operationId: 1 });
    const s = controlReducer(pending, {
      type: "start_succeeded",
      operationId: 1,
      experimentId: EXP_A,
      status: "running",
      config: FIXTURE_CONFIG_A,
    });
    expect(s.activeConfig).toBe(FIXTURE_CONFIG_A);
  });

  it("start_failed clears pending, keeps idle, sets error, remains retryable", () => {
    const pending = controlReducer(initialControlState, { type: "start_requested", operationId: 1 });
    const s = controlReducer(pending, { type: "start_failed", operationId: 1, error: "boom" });
    expect(s.status).toBe("idle");
    expect(s.pending).toBeNull();
    expect(s.error).toBe("boom");
    expect(canStart(s)).toBe(true);
  });
});

describe("pause/resume", () => {
  it("pause_requested rejected unless running", () => {
    const idle = controlReducer(initialControlState, { type: "pause_requested", operationId: 1 });
    expect(idle).toBe(initialControlState);
    const paused = controlReducer(running({ status: "paused" }), { type: "pause_requested", operationId: 1 });
    expect(paused).toEqual(running({ status: "paused" }));
  });

  it("pause_requested -> pause_succeeded transitions to paused", () => {
    const p = controlReducer(running(), { type: "pause_requested", operationId: 1 });
    expect(p.pending).toBe("pause");
    const s = controlReducer(p, { type: "pause_succeeded", operationId: 1, status: "paused" });
    expect(s.status).toBe("paused");
    expect(s.pending).toBeNull();
  });

  it("pause_failed clears pending, leaves status untouched", () => {
    const p = controlReducer(running(), { type: "pause_requested", operationId: 1 });
    const s = controlReducer(p, { type: "pause_failed", operationId: 1, error: "nope" });
    expect(s.status).toBe("running");
    expect(s.pending).toBeNull();
    expect(s.error).toBe("nope");
  });

  it("resume_requested rejected unless paused", () => {
    const s = controlReducer(running(), { type: "resume_requested", operationId: 1 });
    expect(s).toEqual(running());
  });

  it("resume_requested -> resume_succeeded transitions to running", () => {
    const paused = running({ status: "paused" });
    const p = controlReducer(paused, { type: "resume_requested", operationId: 1 });
    expect(p.pending).toBe("resume");
    const s = controlReducer(p, { type: "resume_succeeded", operationId: 1, status: "running" });
    expect(s.status).toBe("running");
    expect(s.pending).toBeNull();
  });
});

describe("speed", () => {
  it("allowed while running or paused, not otherwise", () => {
    expect(canSetSpeed(running())).toBe(true);
    expect(canSetSpeed(running({ status: "paused" }))).toBe(true);
    expect(canSetSpeed(running({ status: "finished" }))).toBe(false);
    expect(canSetSpeed(running({ status: "stopped" }))).toBe(false);
    expect(canSetSpeed(initialControlState)).toBe(false);
  });

  it("speed_succeeded sets speed only on success, never optimistically before", () => {
    const p = controlReducer(running(), { type: "speed_requested", operationId: 1 });
    expect(p.speed).toBe(1);
    const s = controlReducer(p, { type: "speed_succeeded", operationId: 1, speed: 4 });
    expect(s.speed).toBe(4);
    expect(s.pending).toBeNull();
  });

  it("speed_failed leaves the displayed speed unchanged", () => {
    const p = controlReducer(running(), { type: "speed_requested", operationId: 1 });
    const s = controlReducer(p, { type: "speed_failed", operationId: 1, error: "422" });
    expect(s.speed).toBe(1);
    expect(s.error).toBe("422");
  });
});

describe("reset ordering", () => {
  it("reset_requested rejected with no active experiment", () => {
    const s = controlReducer(initialControlState, { type: "reset_requested", operationId: 1 });
    expect(s).toBe(initialControlState);
  });

  it("reset_requested rejected while another action is pending", () => {
    const pending = controlReducer(running(), { type: "pause_requested", operationId: 1 });
    const s = controlReducer(pending, { type: "reset_requested", operationId: 2 });
    expect(s).toBe(pending);
  });

  it("a second reset_requested before resolution is a no-op", () => {
    const r1 = controlReducer(running(), { type: "reset_requested", operationId: 1 });
    const r2 = controlReducer(r1, { type: "reset_requested", operationId: 2 });
    expect(r2).toBe(r1);
  });

  it("reset_create_succeeded atomically swaps experimentId and status", () => {
    const r = controlReducer(running(), { type: "reset_requested", operationId: 1 });
    const s = controlReducer(r, {
      type: "reset_create_succeeded",
      operationId: 1,
      experimentId: EXP_B,
      status: "running",
      config: FIXTURE_CONFIG_B,
    });
    expect(s.experimentId).toBe(EXP_B);
    expect(s.status).toBe("running");
    expect(s.pending).toBeNull();
    expect(s.speed).toBe(1);
  });

  it("reset_create_succeeded updates activeConfig to the new run's config", () => {
    const prevState = { ...running(), activeConfig: FIXTURE_CONFIG_A };
    const r = controlReducer(prevState, { type: "reset_requested", operationId: 1 });
    const s = controlReducer(r, {
      type: "reset_create_succeeded",
      operationId: 1,
      experimentId: EXP_B,
      status: "running",
      config: FIXTURE_CONFIG_B,
    });
    expect(s.activeConfig).toBe(FIXTURE_CONFIG_B);
    expect(s.activeConfig).not.toBe(FIXTURE_CONFIG_A);
  });

  it("stop-succeeded-but-create-failed marks stopped, keeps old id, stays retryable", () => {
    const r = controlReducer(running(), { type: "reset_requested", operationId: 1 });
    const s = controlReducer(r, {
      type: "reset_stop_succeeded_create_failed",
      operationId: 1,
      error: "network down",
    });
    expect(s.experimentId).toBe(EXP_A);
    expect(s.status).toBe("stopped");
    expect(s.pending).toBeNull();
    expect(s.error).toBe("network down");
    expect(canReset(s)).toBe(true);
  });

  it("reset_failed (stop itself failed) leaves state fully untouched but pending cleared", () => {
    const r = controlReducer(running(), { type: "reset_requested", operationId: 1 });
    const s = controlReducer(r, { type: "reset_failed", operationId: 1, error: "timeout" });
    expect(s.experimentId).toBe(EXP_A);
    expect(s.status).toBe("running");
    expect(s.pending).toBeNull();
    expect(s.error).toBe("timeout");
    expect(canReset(s)).toBe(true);
  });
});

describe("activeConfig preservation", () => {
  it("activeConfig is retained across pause_succeeded", () => {
    const withConfig = { ...running(), activeConfig: FIXTURE_CONFIG_A };
    const p = controlReducer(withConfig, { type: "pause_requested", operationId: 1 });
    const s = controlReducer(p, { type: "pause_succeeded", operationId: 1, status: "paused" });
    expect(s.activeConfig).toBe(FIXTURE_CONFIG_A);
  });

  it("activeConfig is retained across resume_succeeded", () => {
    const withConfig = { ...running({ status: "paused" }), activeConfig: FIXTURE_CONFIG_A };
    const p = controlReducer(withConfig, { type: "resume_requested", operationId: 1 });
    const s = controlReducer(p, { type: "resume_succeeded", operationId: 1, status: "running" });
    expect(s.activeConfig).toBe(FIXTURE_CONFIG_A);
  });

  it("activeConfig is retained across speed_succeeded", () => {
    const withConfig = { ...running(), activeConfig: FIXTURE_CONFIG_A };
    const p = controlReducer(withConfig, { type: "speed_requested", operationId: 1 });
    const s = controlReducer(p, { type: "speed_succeeded", operationId: 1, speed: 4 });
    expect(s.activeConfig).toBe(FIXTURE_CONFIG_A);
  });

  it("activeConfig is retained across status_synced", () => {
    const withConfig = { ...running(), activeConfig: FIXTURE_CONFIG_A };
    const s = controlReducer(withConfig, {
      type: "status_synced",
      experimentId: EXP_A,
      revision: 0,
      status: "finished",
    });
    expect(s.activeConfig).toBe(FIXTURE_CONFIG_A);
  });
});

describe("status_synced (polling / stale-id guard)", () => {
  it("applies when the experimentId matches current state", () => {
    const s = controlReducer(running(), {
      type: "status_synced",
      experimentId: EXP_A,
      revision: 0,
      status: "finished",
    });
    expect(s.status).toBe("finished");
  });

  it("is ignored when the experimentId no longer matches (stale poll after Reset swapped ids)", () => {
    const afterReset = running({ experimentId: EXP_B });
    const s = controlReducer(afterReset, {
      type: "status_synced",
      experimentId: EXP_A,
      revision: 0,
      status: "finished",
    });
    expect(s).toBe(afterReset);
  });

  it("ignores a same-experiment poll started before a newer Pause operation", () => {
    const pausePending = controlReducer(running(), {
      type: "pause_requested",
      operationId: 7,
    });
    const paused = controlReducer(pausePending, {
      type: "pause_succeeded",
      operationId: 7,
      status: "paused",
    });
    const stalePoll = controlReducer(paused, {
      type: "status_synced",
      experimentId: EXP_A,
      revision: 0,
      status: "running",
    });
    expect(stalePoll).toBe(paused);
    expect(stalePoll.status).toBe("paused");
  });

  it("ignores a result whose operation id is no longer current", () => {
    const pending = controlReducer(running(), { type: "pause_requested", operationId: 7 });
    const stale = controlReducer(pending, {
      type: "pause_succeeded",
      operationId: 6,
      status: "paused",
    });
    expect(stale).toBe(pending);
  });
});

describe("can* table, exhaustive over status x pending", () => {
  const statuses: ControlStatus[] = ["idle", "running", "paused", "finished", "stopped"];

  it.each(statuses)("status=%s, pending=null", (status) => {
    const s: ControlState = {
      experimentId: status === "idle" ? null : EXP_A,
      status,
      pending: null,
      speed: 1,
      error: null,
      operationId: null,
      revision: 0,
      activeConfig: null,
    };
    expect(canStart(s)).toBe(status === "idle" || status === "finished" || status === "stopped");
    expect(canPause(s)).toBe(status === "running");
    expect(canResume(s)).toBe(status === "paused");
    expect(canSetSpeed(s)).toBe(status === "running" || status === "paused");
    expect(canReset(s)).toBe(status !== "idle");
  });

  it.each(statuses)("status=%s, pending=start blocks every action", (status) => {
    const s: ControlState = {
      experimentId: status === "idle" ? null : EXP_A,
      status,
      pending: "start",
      speed: 1,
      error: null,
      operationId: 1,
      revision: 0,
      activeConfig: null,
    };
    expect(canStart(s)).toBe(false);
    expect(canPause(s)).toBe(false);
    expect(canResume(s)).toBe(false);
    expect(canSetSpeed(s)).toBe(false);
    expect(canReset(s)).toBe(false);
  });
});
