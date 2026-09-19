import type { components } from "@/lib/api/schema.d.ts";

export type NodeView = components["schemas"]["NodeView"];
export type EdgeView = components["schemas"]["EdgeView"];
export type Event = components["schemas"]["Event"];
export type SnapshotFrame = components["schemas"]["SnapshotFrame"];
export type EventFrame = components["schemas"]["EventFrame"];
export type StreamFrame = SnapshotFrame | EventFrame;

export const CURRENT_SCHEMA_VERSION = 1;
export const EVENT_LOG_CAP = 200;
export const INCIDENT_LOG_CAP = 50;

// Event types with per-agent security significance for the incident timeline
// (BRIEF §8). Lifecycle events (EXPERIMENT_*, AGENT_CREATED) are excluded.
// Exported so backend/app/schemas/events.py's INCIDENT_EVENT_TYPES mirror
// (and its cross-language parity test) has something concrete to check
// against on this side too.
export const INCIDENT_EVENT_TYPES = new Set([
  "COMPROMISE_ATTEMPTED",
  "COMPROMISE_SUCCEEDED",
  "COMPROMISE_FAILED",
  "ANOMALY_DETECTED",
  "AGENT_QUARANTINED",
]);

export type GraphState = {
  experimentId: string | null;
  lastSeq: number;
  tick: number;
  nodes: Map<string, NodeView>;
  edges: EdgeView[];
  recentEvents: Event[]; // capped at 200 for the bottom panel
  metrics: {
    // Cumulative count of qualifying COMPROMISE_SUCCEEDED events observed in
    // this live session. Kept outside recentEvents so its 200-event cap cannot
    // silently erase the metric (M1_PLAN §6).
    newCompromises: number;
    // Cumulative count of MODEL_REQUESTED events -- one per real-agent
    // lateral-compromise attempt (docs/PHASE_2_PLAN.md §11). Zero for any
    // experiment with real_agent_count=0, since no MODEL_REQUESTED event is
    // ever emitted in that case.
    modelCalls: number;
  };
  // Per-agent security-incident history, capped at INCIDENT_LOG_CAP per agent.
  // One event may appear under more than one agent (e.g. a COMPROMISE_SUCCEEDED
  // is an incident for both its source and its target).
  incidentsByAgent: Map<string, Event[]>;
};

export const initialGraphState: GraphState = {
  experimentId: null,
  lastSeq: -1,
  tick: 0,
  nodes: new Map(),
  edges: [],
  recentEvents: [],
  metrics: { newCompromises: 0, modelCalls: 0 },
  incidentsByAgent: new Map(),
};

function recordIncident(
  incidentsByAgent: Map<string, Event[]>,
  event: Event,
): Map<string, Event[]> {
  if (!INCIDENT_EVENT_TYPES.has(event.event_type)) {
    return incidentsByAgent;
  }
  const agentIds = new Set<string>();
  if (event.agent_id) agentIds.add(event.agent_id);
  if (event.source_agent_id) agentIds.add(event.source_agent_id);
  if (event.target_agent_id) agentIds.add(event.target_agent_id);
  if (agentIds.size === 0) {
    return incidentsByAgent;
  }

  const next = new Map(incidentsByAgent);
  for (const agentId of agentIds) {
    const existing = next.get(agentId) ?? [];
    next.set(agentId, [...existing, event].slice(-INCIDENT_LOG_CAP));
  }
  return next;
}

/**
 * Metrics not stored in GraphState because they're pure functions of `nodes`
 * (M1's security-state machine only ever moves HEALTHY -> COMPROMISED ->
 * QUARANTINED, and quarantine is terminal — no recovery path exists — so a
 * live tally of current node state is always exactly "ever compromised,"
 * and is automatically correct across a fresh-snapshot reconnect).
 */
export function selectMetrics(state: GraphState): {
  total: number;
  healthy: number;
  compromised: number;
  quarantined: number;
  newCompromises: number;
  totalExposure: number;
  outbreakDuration: number;
  modelCalls: number;
} {
  let healthy = 0;
  let compromised = 0;
  let quarantined = 0;
  for (const node of state.nodes.values()) {
    if (node.security_state === "compromised") compromised += 1;
    else if (node.security_state === "quarantined") quarantined += 1;
    else if (node.security_state === "healthy") healthy += 1;
  }
  return {
    total: state.nodes.size,
    healthy,
    compromised,
    quarantined,
    newCompromises: state.metrics.newCompromises,
    totalExposure: compromised + quarantined,
    outbreakDuration: state.tick,
    modelCalls: state.metrics.modelCalls,
  };
}

/**
 * Pure — no React/DOM dependency, so Phase 1.5 replay can drive it from a
 * stored log with zero changes. Throws on an unrecognized schema_version;
 * the caller is responsible for surfacing that as a hard UI error rather
 * than silently skipping the frame.
 */
export function reduce(state: GraphState, frame: StreamFrame): GraphState {
  if (frame.type === "snapshot") {
    const nodes = new Map<string, NodeView>();
    for (const node of frame.nodes) {
      nodes.set(node.id, node);
    }
    // A snapshot for the same experiment (reconnect) preserves accumulated
    // history; a snapshot for a different (or first-ever) experiment resets
    // it, so no prior experiment's state can leak into a replacement run.
    const sameExperiment = frame.experiment_id === state.experimentId;
    // A brand-new experiment's very first snapshot can already show nodes as
    // compromised/quarantined — the seeded patient-zero compromise always
    // happens server-side before any client can possibly connect (it's
    // published inside the create-experiment request, before the response
    // is even returned), and a slow-to-connect client can miss further
    // ticks the same way. Seed the counter from that snapshot's own tally
    // rather than starting at 0, so newCompromises never silently
    // undercounts compromises that happened before this connection existed.
    const initialExposure = sameExperiment
      ? 0
      : frame.nodes.filter(
          (n) => n.security_state === "compromised" || n.security_state === "quarantined",
        ).length;
    return {
      experimentId: frame.experiment_id,
      lastSeq: frame.last_seq,
      tick: frame.sim_tick,
      nodes,
      edges: frame.edges,
      recentEvents: sameExperiment ? state.recentEvents : [],
      metrics: sameExperiment
        ? state.metrics
        : { newCompromises: initialExposure, modelCalls: 0 },
      incidentsByAgent: sameExperiment ? state.incidentsByAgent : new Map(),
    };
  }

  const event = frame.event;
  if (event.schema_version !== CURRENT_SCHEMA_VERSION) {
    throw new Error(
      `Unrecognized schema_version ${event.schema_version}; this client understands ${CURRENT_SCHEMA_VERSION}.`,
    );
  }

  const recentEvents = [...state.recentEvents, event].slice(-EVENT_LOG_CAP);
  let nodes = state.nodes;

  if (event.event_type === "COMPROMISE_SUCCEEDED" && event.target_agent_id) {
    const existing = state.nodes.get(event.target_agent_id);
    if (existing) {
      nodes = new Map(nodes);
      const isDuplicateClaim = event.metadata?.["already_compromised"] === true;
      nodes.set(event.target_agent_id, {
        ...existing,
        security_state: "compromised",
        ...(isDuplicateClaim
          ? {}
          : {
              compromised_by: event.source_agent_id ?? null,
              tick_compromised: event.sim_tick,
            }),
      });
    }
  }

  if (event.event_type === "AGENT_QUARANTINED" && event.agent_id) {
    const existing = state.nodes.get(event.agent_id);
    if (existing) {
      nodes = new Map(nodes);
      nodes.set(event.agent_id, { ...existing, security_state: "quarantined" });
    }
  }

  let metrics = state.metrics;
  if (event.event_type === "COMPROMISE_SUCCEEDED" && event.metadata?.["already_compromised"] !== true) {
    metrics = { ...metrics, newCompromises: metrics.newCompromises + 1 };
  }
  if (event.event_type === "MODEL_REQUESTED") {
    metrics = { ...metrics, modelCalls: metrics.modelCalls + 1 };
  }

  const incidentsByAgent = recordIncident(state.incidentsByAgent, event);

  return {
    ...state,
    lastSeq: event.seq,
    tick: event.sim_tick,
    nodes,
    recentEvents,
    metrics,
    incidentsByAgent,
  };
}
