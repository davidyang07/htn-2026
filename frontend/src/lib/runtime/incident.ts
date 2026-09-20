// The deny cascade, as four beats a judge can point at.
//
// The backend emits TOOL_REQUESTED → TOOL_DENIED → POLICY_VIOLATION →
// ANOMALY_DETECTED → AGENT_QUARANTINED in a single batch, before the HTTP
// response to the worker is written (app/runtime/session.py
// `request_resource`). That ordering is the product's whole claim — nothing
// was read — so it is surfaced as an ordered cascade rather than as five
// indistinguishable log rows.
//
// Every field here comes off an event. A step is "reached" because the event
// that proves it arrived, and for no other reason.

import type { Event } from "@/lib/stream/reducer";

export type CascadeKey = "requested" | "denied" | "violation" | "quarantined";

export type CascadeStep = {
  key: CascadeKey;
  label: string;
  /** What the event itself said happened. */
  detail: string;
  /** Sequence number of the event that lit this step, or null if not reached. */
  seq: number | null;
};

export type Incident = {
  /** True once a POLICY_VIOLATION has been recorded. */
  detected: boolean;
  workerId: string | null;
  /** Role as registered on AGENT_CREATED, so the banner can name a person. */
  workerRole: string | null;
  /** The path that was requested. Never any content — nothing opened it. */
  resource: string | null;
  /** The deterministic rule that fired, e.g. "protected_path". */
  rule: string | null;
  reason: string | null;
  /** Artifacts the quarantine marked untrusted, as the event listed them. */
  taintedArtifactIds: readonly string[];
  replacementWorkerId: string | null;
  replacementRole: string | null;
  /** The artifacts the replacement was seeded with, per AGENT_CREATED. */
  trustedContextIds: readonly string[];
  /** True when AGENT_STARTED declared a trusted-only context policy. */
  trustedContextOnly: boolean;
  cascade: readonly CascadeStep[];
};

const CASCADE_LABEL: Record<CascadeKey, string> = {
  requested: "Tool request",
  denied: "Request denied",
  violation: "Policy violation",
  quarantined: "Worker quarantined",
};

export const EMPTY_INCIDENT: Incident = {
  detected: false,
  workerId: null,
  workerRole: null,
  resource: null,
  rule: null,
  reason: null,
  taintedArtifactIds: [],
  replacementWorkerId: null,
  replacementRole: null,
  trustedContextIds: [],
  trustedContextOnly: false,
  cascade: [],
};

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

export function deriveIncident(events: readonly Event[]): Incident {
  const roles = new Map<string, string>();
  const reached = new Map<CascadeKey, { seq: number; detail: string }>();

  let detected = false;
  let workerId: string | null = null;
  let resource: string | null = null;
  let rule: string | null = null;
  let reason: string | null = null;
  let taintedArtifactIds: string[] = [];
  let replacementWorkerId: string | null = null;
  let trustedContextIds: string[] = [];
  let trustedContextOnly = false;

  for (const event of events) {
    const meta = (event.metadata ?? {}) as Record<string, unknown>;

    if (event.event_type === "AGENT_CREATED" && event.agent_id) {
      const role = str(meta["role"]);
      if (role) roles.set(event.agent_id, role);
      if (str(meta["replaces"])) {
        replacementWorkerId = event.agent_id;
        trustedContextIds = strings(meta["trusted_context"]);
      }
      continue;
    }

    if (
      event.event_type === "AGENT_STARTED" &&
      event.agent_id === replacementWorkerId &&
      str(meta["context_policy"]) === "trusted_artifacts_only"
    ) {
      trustedContextOnly = true;
      continue;
    }

    switch (event.event_type) {
      case "TOOL_DENIED": {
        // A quarantined worker's later requests are refused too. The cascade
        // must stay pinned to the request that *caused* the quarantine, so a
        // denial is only taken while none has been recorded yet.
        if (reached.has("denied")) break;
        const path = str(meta["resource"]);
        resource = path ?? resource;
        rule = str(meta["violation_type"]) ?? rule;
        reason = str(meta["reason"]) ?? reason;
        reached.set("denied", {
          seq: event.seq,
          detail: "Refused before anything was opened.",
        });
        break;
      }

      case "POLICY_VIOLATION": {
        detected = true;
        workerId = event.agent_id ?? workerId;
        resource = str(meta["resource"]) ?? resource;
        rule = str(meta["violation_type"]) ?? rule;
        reason = str(meta["reason"]) ?? reason;
        if (!reached.has("violation")) {
          reached.set("violation", {
            seq: event.seq,
            detail: str(meta["violation_type"]) ?? "policy violation",
          });
        }
        break;
      }

      case "AGENT_QUARANTINED": {
        if (reached.has("quarantined")) break;
        workerId = event.agent_id ?? workerId;
        taintedArtifactIds = strings(meta["tainted_artifacts"]);
        reached.set("quarantined", {
          seq: event.seq,
          detail: "Removed from the team; its output is untrusted.",
        });
        break;
      }

      default:
        break;
    }
  }

  // The originating request is matched by path rather than by position: the
  // worker made several allowed reads first, and the one that matters is the
  // one that was denied.
  if (resource !== null) {
    for (const event of events) {
      if (event.event_type !== "TOOL_REQUESTED") continue;
      const meta = (event.metadata ?? {}) as Record<string, unknown>;
      if (str(meta["resource"]) !== resource) continue;
      reached.set("requested", { seq: event.seq, detail: resource });
      break;
    }
  }

  const order: CascadeKey[] = ["requested", "denied", "violation", "quarantined"];
  const cascade: CascadeStep[] = order.map((key) => {
    const hit = reached.get(key);
    return {
      key,
      label: CASCADE_LABEL[key],
      detail: hit?.detail ?? "",
      seq: hit?.seq ?? null,
    };
  });

  return {
    detected,
    workerId,
    workerRole: workerId ? (roles.get(workerId) ?? null) : null,
    resource,
    rule,
    reason,
    taintedArtifactIds,
    replacementWorkerId,
    replacementRole: replacementWorkerId ? (roles.get(replacementWorkerId) ?? null) : null,
    trustedContextIds,
    trustedContextOnly,
    cascade,
  };
}
