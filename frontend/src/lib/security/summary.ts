// Derivations over a SecurityGraphView. Pure, so they stay unit-testable
// without a component-rendering setup — the same convention the rest of this
// codebase follows.

import type { SecurityGraphView } from "@/lib/api/client";
import type { Severity } from "@/lib/severity";
import { SECURITY_STATE_SEVERITY } from "@/lib/severity";

export type NonAgentNodeTypeSummary = {
  nodeType: string;
  total: number;
  compromised: number;
};

/**
 * Counts the typed non-agent nodes (tools, credentials, sentinels, ...) that
 * the agent-only stream snapshot cannot describe. Deliberately excludes
 * "agent" — agent counts come from the live stream and the topology graph.
 */
export function summarizeNonAgentNodes(graph: SecurityGraphView): NonAgentNodeTypeSummary[] {
  const counts = new Map<string, { total: number; compromised: number }>();
  for (const node of graph.nodes) {
    if (node.node_type === "agent") continue;
    const entry = counts.get(node.node_type) ?? { total: 0, compromised: 0 };
    entry.total += 1;
    if (node.security_state === "compromised") entry.compromised += 1;
    counts.set(node.node_type, entry);
  }
  return [...counts.entries()]
    .map(([nodeType, { total, compromised }]) => ({ nodeType, total, compromised }))
    .sort((a, b) => a.nodeType.localeCompare(b.nodeType));
}

export type StateTally = Record<string, number>;

/** Security-state histogram across every node of a given type (or all types). */
export function tallySecurityStates(
  graph: SecurityGraphView,
  nodeType?: string,
): StateTally {
  const tally: StateTally = {};
  for (const node of graph.nodes) {
    if (nodeType && node.node_type !== nodeType) continue;
    tally[node.security_state] = (tally[node.security_state] ?? 0) + 1;
  }
  return tally;
}

/** Worst security state present among a set of nodes, as a severity. Used to
 * colour a node-type group by its worst member rather than its average. */
export function worstSeverity(states: readonly string[]): Severity {
  const order: Severity[] = ["neutral", "ok", "contained", "warn", "high", "critical"];
  let worst: Severity = "neutral";
  for (const state of states) {
    const severity = SECURITY_STATE_SEVERITY[state as keyof typeof SECURITY_STATE_SEVERITY];
    if (severity && order.indexOf(severity) > order.indexOf(worst)) worst = severity;
  }
  return worst;
}

/**
 * Ids of every credential/resource node reachable from a compromised node,
 * derived from the blast-radius response. Named separately from the raw
 * `privileged_exposure` count so the UI can list *which* assets are exposed,
 * not just how many.
 */
export function exposedAssets(
  graph: SecurityGraphView,
  reachable: readonly string[],
): Array<{ id: string; nodeType: string; securityState: string }> {
  const reachableSet = new Set(reachable);
  return graph.nodes
    .filter(
      (node) =>
        (node.node_type === "credential" || node.node_type === "resource") &&
        reachableSet.has(node.id),
    )
    .map((node) => ({
      id: node.id,
      nodeType: node.node_type,
      securityState: node.security_state,
    }));
}
