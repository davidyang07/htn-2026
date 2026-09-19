"use client";

import { Badge, SeverityDot } from "@/components/ui/Badge";
import { Meter, StackedBar, StatList, StatRow } from "@/components/ui/Metric";
import { ShapeGlyph } from "@/components/graph/GraphLegend";
import { EmptyState } from "@/components/ui/States";
import type { CriticalNodeView, SecurityGraphView } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { nodeShape } from "@/lib/graph/model";
import { summarizeNonAgentNodes } from "@/lib/security/summary";
import { SECURITY_STATE_LABEL, SECURITY_STATE_SEVERITY, type SecurityState } from "@/lib/severity";
import type { selectMetrics } from "@/lib/stream/reducer";
import { nodeTypeMeta } from "@/lib/vocabulary";

type StreamMetrics = ReturnType<typeof selectMetrics>;

/** How the agent fleet is currently split across security states. */
export function FleetBreakdown({ metrics }: { metrics: StreamMetrics }) {
  const segments = [
    { key: "compromised", value: metrics.compromised, severity: "critical" as const, label: "Compromised" },
    { key: "quarantined", value: metrics.quarantined, severity: "contained" as const, label: "Quarantined" },
    { key: "healthy", value: metrics.healthy, severity: "neutral" as const, label: "Healthy" },
  ];

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <span className="text-2xl font-semibold tracking-tight tabular text-fg">
          {metrics.total}
        </span>
        <span className="text-xs text-fg-subtle">agents under test</span>
      </div>
      <StackedBar segments={segments} />
      <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1">
        {segments.map((segment) => (
          <li key={segment.key} className="flex items-baseline gap-1.5 text-xs">
            <SeverityDot severity={segment.severity} />
            <span className="font-mono tabular text-fg">{segment.value}</span>
            <span className="text-fg-subtle">{segment.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Typed non-agent nodes: what else the attacker can reach besides agents. */
export function AttackSurfacePanel({
  graph,
  onSelectNode,
}: {
  graph: SecurityGraphView | null;
  onSelectNode?: (nodeId: string) => void;
}) {
  const summary = graph ? summarizeNonAgentNodes(graph) : [];

  if (summary.length === 0) {
    return (
      <EmptyState
        compact
        title="Agent mesh only"
        description="This run declares no tools, credentials, resources or sentinels. Add them when launching a run to model access paths and a security plane the attacker can turn."
      />
    );
  }

  return (
    <div className="flex flex-col gap-2.5">
      {summary.map(({ nodeType, total, compromised }) => {
        const meta = nodeTypeMeta(nodeType);
        const severity = compromised > 0 ? "critical" : "ok";
        const nodes = graph?.nodes.filter((n) => n.node_type === nodeType) ?? [];
        return (
          <div key={nodeType}>
            <div className="flex items-baseline gap-2">
              <ShapeGlyph shape={nodeShape(nodeType)} className="shrink-0 text-fg-subtle" />
              <span className="text-xs font-medium text-fg">{meta.plural}</span>
              <span aria-hidden className="min-w-2 flex-1 border-b border-dotted border-line" />
              <span className="font-mono text-xs tabular text-fg">
                {compromised > 0 ? (
                  <span className="text-critical">{compromised}</span>
                ) : (
                  <span className="text-ok">0</span>
                )}
                <span className="text-fg-subtle">/{total}</span>
              </span>
              <span className="text-2xs text-fg-subtle">compromised</span>
            </div>
            <Meter
              className="mt-1.5"
              fraction={total > 0 ? compromised / total : 0}
              severity={severity}
            />
            {compromised > 0 && (
              <ul className="mt-1.5 flex flex-wrap gap-1">
                {nodes
                  .filter((n) => n.security_state === "compromised")
                  .map((node) => (
                    <li key={node.id}>
                      <button
                        type="button"
                        disabled={!onSelectNode}
                        onClick={() => onSelectNode?.(node.id)}
                        className={cn(
                          "rounded-sm bg-critical-soft px-1.5 py-0.5 font-mono text-2xs text-critical ring-1 ring-inset ring-critical/25",
                          onSelectNode && "transition-colors hover:ring-critical/60",
                        )}
                      >
                        {node.id}
                      </button>
                    </li>
                  ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Choke points by betweenness centrality — the nodes whose containment most
 * disconnects the rest of the reachability graph.
 */
export function CriticalNodesPanel({
  nodes,
  graph,
  onSelectNode,
}: {
  nodes: readonly CriticalNodeView[];
  graph: SecurityGraphView | null;
  onSelectNode?: (nodeId: string) => void;
}) {
  if (nodes.length === 0) {
    return <EmptyState compact title="No choke points computed yet" />;
  }
  const max = Math.max(...nodes.map((n) => n.betweenness), 0.0001);
  const stateOf = new Map(graph?.nodes.map((n) => [n.id, n.security_state]) ?? []);

  return (
    <ul className="flex flex-col gap-2">
      {nodes.map((node) => {
        const state = stateOf.get(node.id) as SecurityState | undefined;
        const severity = state ? SECURITY_STATE_SEVERITY[state] : "neutral";
        return (
          <li key={node.id}>
            <button
              type="button"
              disabled={!onSelectNode}
              onClick={() => onSelectNode?.(node.id)}
              className={cn(
                "flex w-full items-baseline gap-2 rounded-sm px-1 py-0.5 text-left",
                onSelectNode && "transition-colors hover:bg-raised",
              )}
            >
              <SeverityDot severity={severity} className="translate-y-[-1px]" />
              <span className="truncate font-mono text-xs text-fg">{node.id}</span>
              {state && state !== "healthy" && (
                <span className="shrink-0 text-2xs text-fg-subtle">
                  {SECURITY_STATE_LABEL[state]}
                </span>
              )}
              <span aria-hidden className="min-w-2 flex-1 border-b border-dotted border-line" />
              <span className="shrink-0 font-mono text-2xs tabular text-fg-muted">
                {node.betweenness.toFixed(3)}
              </span>
            </button>
            <Meter className="mt-1" fraction={node.betweenness / max} severity="neutral" />
          </li>
        );
      })}
    </ul>
  );
}

/** Stream-derived counters that the REST metrics endpoint does not cover. */
export function ObservedCountersPanel({ metrics }: { metrics: StreamMetrics }) {
  return (
    <StatList>
      <StatRow
        label="New compromises"
        value={metrics.newCompromises}
        hint="Distinct successful compromises observed in this session."
        severity={metrics.newCompromises > 0 ? "critical" : "ok"}
      />
      <StatRow
        label="Total exposure"
        value={metrics.totalExposure}
        hint="Agents currently compromised or quarantined."
        severity={metrics.totalExposure > 0 ? "high" : "ok"}
      />
      <StatRow
        label="Outbreak duration"
        value={`${metrics.outbreakDuration} ticks`}
        hint="Simulated ticks elapsed."
      />
      <StatRow
        label="Model calls"
        value={metrics.modelCalls}
        hint="One per LLM-backed lateral-compromise attempt. Zero unless the run has real agents."
      />
    </StatList>
  );
}

export function IncompleteRunNotice() {
  return (
    <Badge severity="warn" title="This run's persisted event log has a detected gap, or was never finalized">
      Incomplete log
    </Badge>
  );
}
