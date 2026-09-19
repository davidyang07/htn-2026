// The single place meaning maps to colour. Every badge, meter, table cell,
// KPI tile and graph node resolves its colour through this module, so a
// "compromised" agent, a critical finding and a failing metric can never
// drift into three different reds across three screens.

import type { NodeView } from "@/lib/stream/reducer";

export type Severity = "critical" | "high" | "warn" | "contained" | "ok" | "neutral";

export type SecurityState = NodeView["security_state"];

/** Human copy for a security state — never render the raw enum. */
export const SECURITY_STATE_LABEL: Record<SecurityState, string> = {
  healthy: "Healthy",
  suspicious: "Suspicious",
  compromised: "Compromised",
  quarantined: "Quarantined",
  recovered: "Recovered",
};

export const SECURITY_STATE_SEVERITY: Record<SecurityState, Severity> = {
  healthy: "neutral",
  suspicious: "warn",
  compromised: "critical",
  quarantined: "contained",
  recovered: "ok",
};

/** One-line explanation of what each state means, for legends and tooltips. */
export const SECURITY_STATE_HINT: Record<SecurityState, string> = {
  healthy: "No policy violation observed.",
  suspicious: "Anomalous behaviour flagged, not yet confirmed.",
  compromised: "Attacker-controlled — a policy violation was observed.",
  quarantined: "Isolated by the defense; can no longer propagate.",
  recovered: "Returned to a trusted state after containment.",
};

/**
 * Hex values mirroring the `--color-*` severity tokens in globals.css.
 * Duplicated here (rather than read from CSS) because WebGL canvas rendering
 * needs literal colours, not custom properties — the graph is the only
 * consumer, and this keeps a single named list to keep in sync.
 */
export const SEVERITY_HEX: Record<Severity, string> = {
  critical: "#f2555f",
  high: "#f5834e",
  warn: "#e0b341",
  contained: "#a273f2",
  ok: "#3fb87a",
  neutral: "#7b8698",
};

/** Tailwind classes per severity, for the three ways severity is presented. */
export const SEVERITY_TEXT: Record<Severity, string> = {
  critical: "text-critical",
  high: "text-high",
  warn: "text-warn",
  contained: "text-contained",
  ok: "text-ok",
  neutral: "text-neutral",
};

export const SEVERITY_BG: Record<Severity, string> = {
  critical: "bg-critical",
  high: "bg-high",
  warn: "bg-warn",
  contained: "bg-contained",
  ok: "bg-ok",
  neutral: "bg-neutral",
};

export const SEVERITY_CHIP: Record<Severity, string> = {
  critical: "bg-critical-soft text-critical ring-critical/25",
  high: "bg-high-soft text-high ring-high/25",
  warn: "bg-warn-soft text-warn ring-warn/25",
  contained: "bg-contained-soft text-contained ring-contained/25",
  ok: "bg-ok-soft text-ok ring-ok/25",
  neutral: "bg-neutral-soft text-fg-muted ring-line-strong/60",
};

/**
 * Severity of a 0..1 fraction where *higher is worse* (compromise fraction,
 * blast radius, attack success rate). Thresholds are presentation-only — the
 * backend makes no such claim — so they are stated once, here, rather than
 * being re-invented per screen.
 */
export function severityForRisk(fraction: number): Severity {
  if (fraction >= 0.5) return "critical";
  if (fraction >= 0.25) return "high";
  if (fraction > 0) return "warn";
  return "ok";
}

/** Severity of a 0..1 fraction where *higher is better* (retained utility,
 * security-plane integrity). */
export function severityForHealth(fraction: number): Severity {
  if (fraction >= 0.9) return "ok";
  if (fraction >= 0.6) return "warn";
  if (fraction >= 0.3) return "high";
  return "critical";
}

export type RunStatus = "idle" | "running" | "paused" | "finished" | "stopped";

export const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  idle: "No run",
  running: "Running",
  paused: "Paused",
  finished: "Complete",
  stopped: "Stopped",
};

export const RUN_STATUS_SEVERITY: Record<RunStatus, Severity> = {
  idle: "neutral",
  running: "ok",
  paused: "warn",
  finished: "neutral",
  stopped: "neutral",
};
