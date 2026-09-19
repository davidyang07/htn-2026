// Presentation-layer formatting. Extracted from the old
// SecurityInsightsPanel/AgentDetailDrawer components so that every screen
// formats a percentage, a latency or a config diff identically, and so the
// logic stays unit-testable without a component-rendering setup (this
// codebase has no jsdom by deliberate choice).

import type { EdgeView, NodeView } from "@/lib/stream/reducer";

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function formatLatency(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(1)} ticks`;
}

export function formatConfigDiff(diff: Record<string, unknown>): string {
  const entries = Object.entries(diff);
  if (entries.length === 0) return "(no change)";
  return entries.map(([key, value]) => `${key} → ${JSON.stringify(value)}`).join(", ");
}

export function formatProvenanceChain(chain: string[]): string {
  if (chain.length === 0) return "(no provenance chain)";
  return chain.join(" → ");
}

/** First segment of a UUID — enough to identify a run in a table without
 * spending a whole column on it. */
export function shortId(id: string): string {
  return id.slice(0, 8);
}

export function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Compact metadata rendering for the event log: `key=value` pairs rather
 * than raw JSON braces, which are pure noise at log density. */
export function formatEventMetadata(metadata: Record<string, unknown> | null | undefined): string {
  if (!metadata) return "";
  const entries = Object.entries(metadata);
  if (entries.length === 0) return "";
  return entries
    .map(([key, value]) => `${key}=${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join("  ");
}

export function deriveNeighbors(nodeId: string, edges: EdgeView[]): string[] {
  return edges
    .filter((e) => e.source === nodeId || e.target === nodeId)
    .map((e) => (e.source === nodeId ? e.target : e.source));
}

export function describeCompromisedBy(node: NodeView): string {
  const isCompromisedOrQuarantined =
    node.security_state === "compromised" || node.security_state === "quarantined";
  if (!isCompromisedOrQuarantined) {
    return "—";
  }
  if (node.compromised_by != null) {
    return node.compromised_by;
  }
  // The seeded initial compromise (BRIEF's "patient zero") genuinely has no
  // source agent — tick_compromised === 0 is how build_world() marks it —
  // so it's a known fact, not data lost before this session connected.
  if (node.tick_compromised === 0) {
    return "— (initial compromise)";
  }
  return "unknown (before this session's connection)";
}

export function describeTickCompromised(node: NodeView): string {
  const isCompromisedOrQuarantined =
    node.security_state === "compromised" || node.security_state === "quarantined";
  if (isCompromisedOrQuarantined && node.compromised_by == null && node.tick_compromised !== 0) {
    return "unknown (before this session's connection)";
  }
  return node.tick_compromised === null || node.tick_compromised === undefined
    ? "—"
    : String(node.tick_compromised);
}
