import type { ExperimentConfig } from "@/lib/api/client";

/** SPEC §6.2's canonical demo config, plus the security-graph and scenario
 * fields the backend defaults — stated explicitly so the form always shows
 * the same values the backend would apply. */
export const DEFAULT_CONFIG: ExperimentConfig = {
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
  active_scenarios: ["propagation", "prompt_injection"],
  adaptive_detection_threshold: 0.3,
  false_quarantine_rate: 0,
  sentinel_compromise_rate: 0,
  attestation_replay_rate: 0,
  byzantine_collusion_rate: 0,
};

/**
 * Backend `Field(...)` bounds, mirrored for UX only — the backend remains the
 * source of truth and re-validates every value (BRIEF §6).
 */
export const BOUNDS = {
  node_count: [25, 100],
  edge_density: [1, 5],
  software_type_count: [1, 5],
  p_same: [0, 1],
  p_cross: [0, 1],
  max_ticks: [1, 2000],
  detector_sensitivity: [0, 1],
  real_agent_count: [0, 20],
  tool_count: [0, 20],
  credential_count: [0, 20],
  resource_count: [0, 20],
  sentinel_count: [0, 5],
  adaptive_detection_threshold: [0, 1],
  false_quarantine_rate: [0, 1],
  sentinel_compromise_rate: [0, 1],
  attestation_replay_rate: [0, 1],
  byzantine_collusion_rate: [0, 1],
} as const satisfies Record<string, readonly [number, number]>;

export function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.min(max, Math.max(min, value));
}

export type Preset = {
  id: string;
  label: string;
  description: string;
  config: ExperimentConfig;
};

/**
 * Starting points, not magic. Each is an ordinary `ExperimentConfig` the form
 * loads and the user can then edit — they exist because "which of 24 fields
 * do I change to see a sentinel get subverted?" is not a question a first-time
 * viewer should have to answer.
 */
export const PRESETS: readonly Preset[] = [
  {
    id: "baseline",
    label: "Baseline propagation",
    description:
      "Homogeneous agent mesh, lateral compromise spread, anomaly-detection defense enabled.",
    config: DEFAULT_CONFIG,
  },
  {
    id: "undefended",
    label: "Undefended control",
    description:
      "The same system with the defense switched off — the control arm for any defense claim.",
    config: {
      ...DEFAULT_CONFIG,
      defense_enabled: false,
      tool_count: 6,
      credential_count: 4,
      resource_count: 3,
      sentinel_count: 2,
      active_scenarios: ["propagation"],
    },
  },
  {
    id: "security-plane",
    label: "Security-plane assault",
    description:
      "Tools, credentials and sentinels in play; the attacker subverts a sentinel, replays an attestation, and colludes to exceed credential scope.",
    config: {
      ...DEFAULT_CONFIG,
      max_ticks: 120,
      tool_count: 6,
      credential_count: 4,
      resource_count: 3,
      sentinel_count: 2,
      sentinel_compromise_rate: 0.08,
      attestation_replay_rate: 0.05,
      byzantine_collusion_rate: 0.05,
      false_quarantine_rate: 0.05,
      active_scenarios: [
        "propagation",
        "sentinel_compromise",
        "attestation",
        "byzantine_collusion",
      ],
    },
  },
  {
    id: "adaptive",
    label: "Adaptive attacker",
    description:
      "An attacker that watches the quarantine rate each tick and switches between aggressive and stealthy targeting.",
    config: {
      ...DEFAULT_CONFIG,
      seed: 7,
      node_count: 80,
      max_ticks: 150,
      detector_sensitivity: 0.5,
      tool_count: 8,
      credential_count: 5,
      resource_count: 4,
      sentinel_count: 3,
      active_scenarios: ["adaptive_attacker"],
    },
  },
] as const;
