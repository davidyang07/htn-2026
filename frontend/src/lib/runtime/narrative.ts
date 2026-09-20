// The run as a story, not as a log.
//
// A real run emits ~54 events, and roughly forty of them are "this worker read
// a file" and "this worker called a model". Those are load-bearing for an
// operator grepping the stream and worthless to someone being shown the
// product for the first time: the thirteen beats that matter drown in them.
//
// So the stream is folded. A milestone — the ones a judge is meant to read —
// keeps its own row and gets written copy plus the real metadata behind it.
// Everything else collapses into the worker that produced it: "Security
// Researcher working · 2 files read, 1 model call". Nothing is dropped; the
// full stream stays one toggle away, and a group states exactly what it folded.

import type { Severity } from "@/lib/severity";
import type { Event } from "@/lib/stream/reducer";

export type Beat = {
  /** Anchor event's id — stable across re-renders and re-backfills. */
  id: string;
  seq: number;
  tick: number;
  wallTime: string;
  kind: "milestone" | "activity";
  severity: Severity;
  label: string;
  /** Real metadata, never a paraphrase of it. Empty when there is none. */
  detail: string;
  /** Worker id the beat belongs to, when it belongs to one. */
  actor: string | null;
  /** Role as registered, so a beat can name a person rather than an id. */
  actorRole: string | null;
  /** How many raw events this beat stands for. 1 for a milestone. */
  count: number;
};

/** Human copy for the low-level events an activity beat folds up. */
const ACTIVITY_NOUN: Record<string, [string, string]> = {
  TOOL_REQUESTED: ["file requested", "files requested"],
  TOOL_EXECUTED: ["file read", "files read"],
  MODEL_REQUESTED: ["model call", "model calls"],
  MEMORY_READ: ["memory read", "memory reads"],
  MEMORY_WRITE: ["memory write", "memory writes"],
  MESSAGE_SENT: ["message", "messages"],
  MESSAGE_RECEIVED: ["message", "messages"],
  AGENT_CREATED: ["worker registered", "workers registered"],
};

/**
 * Events that never become a beat of their own.
 *
 * MODEL_RESPONDED is dropped rather than folded because it duplicates
 * MODEL_REQUESTED exactly — counting both would report twice the model calls
 * that were actually made.
 */
const SILENT = new Set(["MODEL_RESPONDED", "AGENT_STOPPED"]);

/** Step names in TASK_COMPLETED that deserve written copy of their own. */
const STEP_COPY: Record<string, { label: string; severity: Severity }> = {
  analysis: { label: "Repository analysed", severity: "neutral" },
  research: { label: "Vulnerability investigated", severity: "neutral" },
  regression_test: { label: "Regression coverage added", severity: "neutral" },
  vulnerability_proven: { label: "Vulnerability reproduced", severity: "warn" },
  vulnerability_NOT_proven: { label: "Vulnerability NOT reproduced", severity: "high" },
  patch: { label: "Patch applied", severity: "neutral" },
  review: { label: "Independently reviewed", severity: "ok" },
};

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function plural(count: number, [one, many]: [string, string]): string {
  return `${count} ${count === 1 ? one : many}`;
}

type Milestone = { label: string; severity: Severity; detail: string } | null;

function milestoneFor(event: Event, replacementIds: ReadonlySet<string>): Milestone {
  const meta = (event.metadata ?? {}) as Record<string, unknown>;

  switch (event.event_type) {
    case "TASK_ASSIGNED":
      return { label: "Task assigned", severity: "neutral", detail: str(meta["task"]) };

    case "TOOL_DENIED":
      return {
        label: "AgentShield denied the request",
        severity: "critical",
        detail: str(meta["resource"]),
      };

    case "POLICY_VIOLATION":
      return {
        label: "Policy violation",
        severity: "critical",
        detail: str(meta["reason"]) || str(meta["violation_type"]),
      };

    case "ANOMALY_DETECTED":
      return {
        label: "Anomaly detected",
        severity: "warn",
        detail: str(meta["detector"]),
      };

    case "AGENT_QUARANTINED":
      return {
        label: "Worker quarantined",
        severity: "contained",
        detail: str(meta["reason"]),
      };

    case "TASK_REASSIGNED":
      return {
        label: "Task reassigned",
        severity: "contained",
        detail: event.target_agent_id ? `to ${event.target_agent_id}` : str(meta["task"]),
      };

    case "AGENT_CREATED":
      return str(meta["replaces"])
        ? {
            label: "Replacement worker created",
            severity: "contained",
            detail: `replaces ${str(meta["replaces"])}`,
          }
        : null;

    case "AGENT_STARTED":
      return event.agent_id && replacementIds.has(event.agent_id)
        ? {
            label: "Replacement started on trusted context only",
            severity: "ok",
            detail: str(meta["context_policy"]),
          }
        : null;

    case "AGENT_RECOVERED":
      return { label: "Worker recovered", severity: "ok", detail: "" };

    case "TASK_COMPLETED": {
      const step = str(meta["step"]);
      if (step === "pytest") {
        // The run's own words, and its own colour: a red run reads red.
        const passed = meta["passed"] === true;
        return {
          label: passed ? "Regression suite passed" : "Regression suite failed",
          severity: passed ? "ok" : "critical",
          detail: str(meta["detail"]),
        };
      }
      const copy = STEP_COPY[step];
      if (copy) return { ...copy, detail: str(meta["detail"]) };
      return step ? { label: step, severity: "neutral", detail: str(meta["detail"]) } : null;
    }

    case "WORKFLOW_RECOVERED":
      return { label: "Workflow recovered", severity: "ok", detail: str(meta["summary"]) };

    case "EXPERIMENT_STOPPED":
      return { label: "Workflow stopped", severity: "high", detail: str(meta["reason"]) };

    default:
      return null;
  }
}

export function deriveNarrative(events: readonly Event[]): Beat[] {
  const roles = new Map<string, string>();
  const replacementIds = new Set<string>();
  for (const event of events) {
    if (event.event_type !== "AGENT_CREATED" || !event.agent_id) continue;
    const meta = (event.metadata ?? {}) as Record<string, unknown>;
    const role = str(meta["role"]);
    if (role) roles.set(event.agent_id, role);
    if (str(meta["replaces"])) replacementIds.add(event.agent_id);
  }

  const beats: Beat[] = [];
  // The open activity run, if the previous event folded into one.
  let open: { beat: Beat; counts: Map<string, number> } | null = null;

  const closeActivity = () => {
    if (!open) return;
    const parts = [...open.counts.entries()]
      .filter(([type]) => ACTIVITY_NOUN[type])
      .map(([type, count]) => plural(count, ACTIVITY_NOUN[type]!));
    open.beat.detail = parts.join(", ");
    open = null;
  };

  for (const event of events) {
    if (SILENT.has(event.event_type)) continue;

    const milestone = milestoneFor(event, replacementIds);
    if (milestone) {
      closeActivity();
      beats.push({
        id: event.event_id,
        seq: event.seq,
        tick: event.sim_tick,
        wallTime: event.wall_time,
        kind: "milestone",
        severity: milestone.severity,
        label: milestone.label,
        detail: milestone.detail,
        actor: event.agent_id ?? null,
        actorRole: event.agent_id ? (roles.get(event.agent_id) ?? null) : null,
        count: 1,
      });
      continue;
    }

    // Registering the team is one beat about the team, not four beats about
    // four workers who have not done anything yet.
    const teamScope = event.event_type === "AGENT_CREATED";
    const actor = teamScope ? null : (event.agent_id ?? null);
    const label = teamScope
      ? "Team assembled"
      : actor
        ? `${roles.get(actor) ?? actor} working`
        : "Session activity";

    // Folded by label rather than by actor: "the team did 9 things" is not a
    // sentence anyone can act on, and two beats that read identically should
    // never sit next to each other either.
    if (open && open.beat.label === label) {
      open.beat.count += 1;
      open.counts.set(event.event_type, (open.counts.get(event.event_type) ?? 0) + 1);
      continue;
    }

    closeActivity();
    const beat: Beat = {
      id: event.event_id,
      seq: event.seq,
      tick: event.sim_tick,
      wallTime: event.wall_time,
      kind: "activity",
      severity: "neutral",
      label,
      detail: "",
      actor,
      actorRole: actor ? (roles.get(actor) ?? null) : null,
      count: 1,
    };
    beats.push(beat);
    open = { beat, counts: new Map([[event.event_type, 1]]) };
  }

  closeActivity();
  return beats;
}
