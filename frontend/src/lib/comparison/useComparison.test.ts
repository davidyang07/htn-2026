import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ExperimentConfig, MetricsResponse } from "@/lib/api/client";

import { loadHistoricalArm } from "./loadHistoricalArm";
import { runExperimentToCompletion } from "./runToCompletion";
import {
  buildComparisonConfigs,
  runBothArms,
  runBothHistoricalArms,
  type ArmResult,
} from "./useComparison";

vi.mock("./runToCompletion", () => ({
  runExperimentToCompletion: vi.fn(),
}));

vi.mock("./loadHistoricalArm", () => ({
  loadHistoricalArm: vi.fn(),
}));

const mockedRun = vi.mocked(runExperimentToCompletion);
const mockedLoadHistorical = vi.mocked(loadHistoricalArm);

const BASE_CONFIG: ExperimentConfig = {
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

function withoutDefenseEnabled(config: ExperimentConfig): Omit<ExperimentConfig, "defense_enabled"> {
  return Object.fromEntries(
    Object.entries(config).filter(([key]) => key !== "defense_enabled"),
  ) as Omit<ExperimentConfig, "defense_enabled">;
}

function fakeMetrics(overrides: Partial<MetricsResponse> = {}): MetricsResponse {
  return {
    compromise_fraction: 0.1,
    retained_utility: 0.8,
    blast_radius_fraction: 0.2,
    privileged_exposure: 1,
    security_plane_integrity: 1,
    attack_success_rate: 0.3,
    false_quarantine_rate: 0,
    detection_latency: 1,
    containment_latency: 1,
    ...overrides,
  };
}

describe("buildComparisonConfigs", () => {
  it("produces two configs identical to baseConfig except defense_enabled", () => {
    const [configA, configB] = buildComparisonConfigs(BASE_CONFIG);

    expect(configA).toEqual({ ...BASE_CONFIG, defense_enabled: true });
    expect(configB).toEqual({ ...BASE_CONFIG, defense_enabled: false });

    expect(configA.defense_enabled).toBe(true);
    expect(configB.defense_enabled).toBe(false);

    // Differ from each other only in defense_enabled.
    expect(withoutDefenseEnabled(configA)).toEqual(withoutDefenseEnabled(configB));
  });

  it("does not mutate baseConfig", () => {
    const snapshot = { ...BASE_CONFIG };
    buildComparisonConfigs(BASE_CONFIG);
    expect(BASE_CONFIG).toEqual(snapshot);
  });
});

describe("runBothArms", () => {
  beforeEach(() => {
    mockedRun.mockReset();
  });

  it("reports each arm's outcome exactly once; A's success and B's failure don't affect each other", async () => {
    const metricsA = fakeMetrics({ compromise_fraction: 0.3 });
    mockedRun.mockImplementation(async (config: ExperimentConfig) => {
      if (config.defense_enabled) {
        return { experimentId: "exp-a", metrics: metricsA };
      }
      throw new Error("arm B blew up");
    });

    const updates: Array<{ arm: "A" | "B"; result: ArmResult }> = [];
    const onArmUpdate = vi.fn((arm: "A" | "B", result: ArmResult) => {
      updates.push({ arm, result });
    });

    await runBothArms(BASE_CONFIG, onArmUpdate);

    expect(onArmUpdate).toHaveBeenCalledTimes(2);

    const a = updates.find((u) => u.arm === "A")!;
    const b = updates.find((u) => u.arm === "B")!;

    expect(a.result).toEqual({ metrics: metricsA });
    expect(b.result).toEqual({ error: "arm B blew up" });
  });

  it("reports each arm's outcome exactly once; A's failure and B's success don't affect each other", async () => {
    const metricsB = fakeMetrics({ compromise_fraction: 0.9 });
    mockedRun.mockImplementation(async (config: ExperimentConfig) => {
      if (config.defense_enabled) {
        throw new Error("arm A blew up");
      }
      return { experimentId: "exp-b", metrics: metricsB };
    });

    const updates: Array<{ arm: "A" | "B"; result: ArmResult }> = [];
    const onArmUpdate = vi.fn((arm: "A" | "B", result: ArmResult) => {
      updates.push({ arm, result });
    });

    await runBothArms(BASE_CONFIG, onArmUpdate);

    expect(onArmUpdate).toHaveBeenCalledTimes(2);

    const a = updates.find((u) => u.arm === "A")!;
    const b = updates.find((u) => u.arm === "B")!;

    expect(a.result).toEqual({ error: "arm A blew up" });
    expect(b.result).toEqual({ metrics: metricsB });
  });

  it("calls runExperimentToCompletion with the two derived configs (defense on/off)", async () => {
    mockedRun.mockResolvedValue({ experimentId: "exp", metrics: fakeMetrics() });

    await runBothArms(BASE_CONFIG, vi.fn());

    expect(mockedRun).toHaveBeenCalledTimes(2);
    const calledConfigs = mockedRun.mock.calls.map(([config]) => config);
    expect(calledConfigs).toContainEqual({ ...BASE_CONFIG, defense_enabled: true });
    expect(calledConfigs).toContainEqual({ ...BASE_CONFIG, defense_enabled: false });
  });

  it("converts non-Error throws to a string message", async () => {
    mockedRun.mockImplementation(async (config: ExperimentConfig) => {
      if (config.defense_enabled) {
        return { experimentId: "exp-a", metrics: fakeMetrics() };
      }
      throw "plain string failure";
    });

    const onArmUpdate = vi.fn();
    await runBothArms(BASE_CONFIG, onArmUpdate);

    expect(onArmUpdate).toHaveBeenCalledWith("B", { error: "plain string failure" });
  });
});

describe("runBothHistoricalArms", () => {
  beforeEach(() => {
    mockedLoadHistorical.mockReset();
  });

  it("loads both historical arms independently and reports incomplete alongside metrics", async () => {
    mockedLoadHistorical.mockImplementation(async (experimentId: string) => {
      if (experimentId === "exp-a") {
        return { experimentId, metrics: fakeMetrics({ compromise_fraction: 0.3 }), incomplete: false };
      }
      return { experimentId, metrics: fakeMetrics({ compromise_fraction: 0.6 }), incomplete: true };
    });

    const updates: Array<{ arm: "A" | "B"; result: ArmResult }> = [];
    await runBothHistoricalArms("exp-a", "exp-b", (arm, result) => updates.push({ arm, result }));

    expect(mockedLoadHistorical).toHaveBeenCalledTimes(2);
    expect(mockedLoadHistorical).toHaveBeenCalledWith("exp-a");
    expect(mockedLoadHistorical).toHaveBeenCalledWith("exp-b");

    const a = updates.find((u) => u.arm === "A")!;
    const b = updates.find((u) => u.arm === "B")!;
    expect(a.result).toEqual({ metrics: fakeMetrics({ compromise_fraction: 0.3 }), incomplete: false });
    expect(b.result).toEqual({ metrics: fakeMetrics({ compromise_fraction: 0.6 }), incomplete: true });
  });

  it("A's failure and B's success don't affect each other", async () => {
    mockedLoadHistorical.mockImplementation(async (experimentId: string) => {
      if (experimentId === "exp-a") throw new Error("exp-a not found");
      return { experimentId, metrics: fakeMetrics(), incomplete: false };
    });

    const updates: Array<{ arm: "A" | "B"; result: ArmResult }> = [];
    await runBothHistoricalArms("exp-a", "exp-b", (arm, result) => updates.push({ arm, result }));

    const a = updates.find((u) => u.arm === "A")!;
    const b = updates.find((u) => u.arm === "B")!;
    expect(a.result).toEqual({ error: "exp-a not found" });
    expect("error" in b.result).toBe(false);
  });
});
