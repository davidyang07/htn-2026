// Product vocabulary: how the backend's machine names are spoken in the UI.
//
// The old dashboard rendered raw enum members and snake_case config keys
// directly ("COMPROMISE_SUCCEEDED", "p_cross"). Machine names still appear —
// they are the contract, and an operator reproducing a run needs them — but
// they now appear *alongside* a human label, never instead of one.

import type { Severity } from "@/lib/severity";

export type EventCategory = "attack" | "defense" | "model" | "lifecycle" | "security-plane";

export type EventMeta = {
  label: string;
  category: EventCategory;
  severity: Severity;
};

const ATTACK = (label: string, severity: Severity): EventMeta => ({
  label,
  category: "attack",
  severity,
});
const DEFENSE = (label: string, severity: Severity): EventMeta => ({
  label,
  category: "defense",
  severity,
});
const PLANE = (label: string, severity: Severity): EventMeta => ({
  label,
  category: "security-plane",
  severity,
});
const MODEL = (label: string): EventMeta => ({ label, category: "model", severity: "neutral" });
const LIFECYCLE = (label: string): EventMeta => ({
  label,
  category: "lifecycle",
  severity: "neutral",
});

export const EVENT_META: Record<string, EventMeta> = {
  EXPERIMENT_STARTED: LIFECYCLE("Assessment started"),
  EXPERIMENT_STOPPED: LIFECYCLE("Assessment stopped"),
  AGENT_CREATED: LIFECYCLE("Agent registered"),
  AGENT_STARTED: LIFECYCLE("Agent started"),
  AGENT_STOPPED: LIFECYCLE("Agent stopped"),
  MESSAGE_SENT: LIFECYCLE("Message sent"),
  MESSAGE_RECEIVED: LIFECYCLE("Message received"),

  MODEL_REQUESTED: MODEL("Model call"),
  MODEL_RESPONDED: MODEL("Model response"),
  TOOL_REQUESTED: MODEL("Tool requested"),
  TOOL_EXECUTED: MODEL("Tool executed"),
  TOOL_DENIED: DEFENSE("Tool denied", "warn"),
  MEMORY_READ: MODEL("Memory read"),
  MEMORY_WRITE: MODEL("Memory write"),

  CREDENTIAL_ACCESSED: ATTACK("Credential accessed", "warn"),
  CREDENTIAL_REVOKED: DEFENSE("Credential revoked", "ok"),

  COMPROMISE_ATTEMPTED: ATTACK("Compromise attempted", "warn"),
  COMPROMISE_SUCCEEDED: ATTACK("Compromise succeeded", "critical"),
  COMPROMISE_FAILED: ATTACK("Compromise blocked", "ok"),
  POLICY_VIOLATION: ATTACK("Policy violation", "critical"),

  ANOMALY_DETECTED: DEFENSE("Anomaly detected", "warn"),
  AGENT_QUARANTINED: DEFENSE("Agent quarantined", "contained"),
  AGENT_RELEASED: DEFENSE("Agent released", "ok"),
  AGENT_RECOVERED: DEFENSE("Agent recovered", "ok"),
  PERMISSION_CHANGED: DEFENSE("Permission changed", "neutral"),
  INFERENCE_DISABLED: DEFENSE("Inference disabled", "contained"),

  THREAT_SIGNATURE_PUBLISHED: PLANE("Threat signature published", "warn"),
  THREAT_SIGNATURE_RECEIVED: PLANE("Threat signature received", "neutral"),
  ATTESTATION_ISSUED: PLANE("Attestation issued", "neutral"),
  ATTESTATION_VERIFIED: PLANE("Attestation verified", "neutral"),
};

export function eventMeta(eventType: string): EventMeta {
  return EVENT_META[eventType] ?? LIFECYCLE(eventType);
}

/**
 * Some events change severity based on metadata — a verified attestation is
 * routine, a *replayed* one is an attack; a quarantine is a win unless it was
 * illegitimate. Encoding that here keeps the event table honest.
 */
export function eventSeverity(
  eventType: string,
  metadata: Record<string, unknown> | null | undefined,
): Severity {
  if (eventType === "ATTESTATION_VERIFIED" && metadata?.["replayed"] === true) return "critical";
  if (eventType === "AGENT_QUARANTINED" && metadata?.["legitimate"] === false) return "high";
  if (eventType === "THREAT_SIGNATURE_PUBLISHED" && metadata?.["legitimate"] === false)
    return "high";
  if (eventType === "COMPROMISE_SUCCEEDED" && metadata?.["already_compromised"] === true)
    return "warn";
  return eventMeta(eventType).severity;
}

export const EVENT_CATEGORY_LABEL: Record<EventCategory, string> = {
  attack: "Attack",
  defense: "Defense",
  "security-plane": "Security plane",
  model: "Model / tool",
  lifecycle: "Lifecycle",
};

// --- Security-graph node types -------------------------------------------

export type GraphNodeType =
  | "agent"
  | "tool"
  | "mcp_server"
  | "credential"
  | "resource"
  | "memory_store"
  | "sentinel"
  | "security_control";

export type NodeTypeMeta = {
  label: string;
  plural: string;
  /** Which plane the node belongs to — drives grouping and graph layering. */
  plane: "workload" | "data" | "security";
  hint: string;
};

export const NODE_TYPE_META: Record<GraphNodeType, NodeTypeMeta> = {
  agent: {
    label: "Agent",
    plural: "Agents",
    plane: "workload",
    hint: "An autonomous actor in the system. Compromise spreads between agents.",
  },
  tool: {
    label: "Tool",
    plural: "Tools",
    plane: "workload",
    hint: "A callable capability an agent can invoke.",
  },
  mcp_server: {
    label: "MCP server",
    plural: "MCP servers",
    plane: "workload",
    hint: "A tool-hosting server reachable by agents.",
  },
  credential: {
    label: "Credential",
    plural: "Credentials",
    plane: "data",
    hint: "A secret an agent holds to unlock access to a resource.",
  },
  resource: {
    label: "Resource",
    plural: "Resources",
    plane: "data",
    hint: "A protected asset reachable through a credential.",
  },
  memory_store: {
    label: "Memory store",
    plural: "Memory stores",
    plane: "data",
    hint: "An agent's persistent memory — a poisoning target.",
  },
  sentinel: {
    label: "Sentinel",
    plural: "Sentinels",
    plane: "security",
    hint: "A monitor watching agents, with authority to quarantine them.",
  },
  security_control: {
    label: "Security control",
    plural: "Security controls",
    plane: "security",
    hint: "Control-plane service: trust manager, threat memory, attestation, quarantine.",
  },
};

export function nodeTypeMeta(nodeType: string): NodeTypeMeta {
  return (
    NODE_TYPE_META[nodeType as GraphNodeType] ?? {
      label: nodeType,
      plural: nodeType,
      plane: "workload",
      hint: "",
    }
  );
}

export const PLANE_LABEL: Record<NodeTypeMeta["plane"], string> = {
  workload: "Workload plane",
  data: "Data plane",
  security: "Security plane",
};

// --- Edge types -----------------------------------------------------------

export type GraphEdgeType =
  | "communicates_with"
  | "delegates_to"
  | "trusts"
  | "can_access"
  | "uses_credential"
  | "monitors"
  | "quarantine_authority"
  | "updates_threat_memory";

/** Which visual layer an edge belongs to. Layers are independently toggleable
 * in the topology view — a 650-edge graph is unreadable with all of them on. */
export type EdgeLayer = "mesh" | "access" | "oversight";

export const EDGE_LAYER_OF: Record<GraphEdgeType, EdgeLayer> = {
  communicates_with: "mesh",
  delegates_to: "mesh",
  trusts: "mesh",
  can_access: "access",
  uses_credential: "access",
  monitors: "oversight",
  quarantine_authority: "oversight",
  updates_threat_memory: "oversight",
};

export const EDGE_LAYER_META: Record<
  EdgeLayer,
  { label: string; hint: string; color: string }
> = {
  mesh: {
    label: "Communication",
    hint: "Agent-to-agent messaging and trust — the path compromise propagates along.",
    color: "#2b3340",
  },
  access: {
    label: "Access",
    hint: "Which agents can reach which tools, credentials and resources.",
    color: "#3a4c63",
  },
  oversight: {
    label: "Oversight",
    hint: "Which sentinels monitor which agents, and who holds quarantine authority.",
    color: "#3d3357",
  },
};

// --- Attack scenarios -----------------------------------------------------

export type ScenarioMeta = {
  /** Backend registry key — sent verbatim in `active_scenarios`. */
  value: string;
  label: string;
  hint: string;
  /** Config fields that must be non-zero for the scenario to do anything. */
  requires?: string[];
  /** Owns the tick increment, so it cannot be combined with another such
   * scenario (docs/PLAN.md §4). */
  exclusiveWith?: string[];
};

export const SCENARIOS: readonly ScenarioMeta[] = [
  {
    value: "propagation",
    label: "Lateral propagation",
    hint: "Probabilistic compromise spread along communication edges, faster within a software type than across.",
    exclusiveWith: ["adaptive_attacker"],
  },
  {
    value: "adaptive_attacker",
    label: "Adaptive attacker",
    hint: "Observes the quarantine rate each tick and switches between aggressive and stealthy targeting.",
    exclusiveWith: ["propagation"],
  },
  {
    value: "prompt_injection",
    label: "Indirect prompt injection",
    hint: "A compromised LLM-backed agent tries to extract a neighbour's confidential token. Needs real agents.",
    requires: ["real_agent_count"],
  },
  {
    value: "sentinel_compromise",
    label: "Sentinel subversion",
    hint: "A sentinel watching a compromised agent is itself subverted, then suppresses detection and poisons threat memory.",
    requires: ["sentinel_count", "sentinel_compromise_rate"],
  },
  {
    value: "attestation",
    label: "Attestation replay",
    hint: "A compromised agent presents a stale attestation nonce and is accepted.",
    requires: ["sentinel_count", "attestation_replay_rate"],
  },
  {
    value: "byzantine_collusion",
    label: "Byzantine collusion",
    hint: "Two compromised agents jointly exceed credential scope on a credential neither legitimately holds.",
    requires: ["credential_count", "byzantine_collusion_rate"],
  },
] as const;

export function scenarioMeta(value: string): ScenarioMeta {
  return SCENARIOS.find((s) => s.value === value) ?? { value, label: value, hint: "" };
}

// --- Config field labels --------------------------------------------------

/** Human label for each `ExperimentConfig` key the UI surfaces. The machine
 * key stays visible next to it wherever reproducibility matters. */
export const CONFIG_LABEL: Record<string, string> = {
  seed: "Seed",
  node_count: "Agents",
  edge_density: "Edge density",
  software_type_count: "Software diversity",
  p_same: "Same-stack infection rate",
  p_cross: "Cross-stack infection rate",
  max_ticks: "Max ticks",
  detector_sensitivity: "Detector sensitivity",
  defense_enabled: "Defense",
  initial_compromised: "Initial foothold",
  real_agent_count: "LLM-backed agents",
  model_provider: "Model provider",
  tool_count: "Tools",
  credential_count: "Credentials",
  resource_count: "Resources",
  sentinel_count: "Sentinels",
  adaptive_detection_threshold: "Adaptive threshold",
  false_quarantine_rate: "False-quarantine rate",
  sentinel_compromise_rate: "Sentinel-subversion rate",
  attestation_replay_rate: "Attestation-replay rate",
  byzantine_collusion_rate: "Collusion rate",
  active_scenarios: "Attack scenarios",
};

export function configLabel(key: string): string {
  return CONFIG_LABEL[key] ?? key;
}
