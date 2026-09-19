"use client";

import { EventRow } from "@/components/activity/EventRow";
import { Badge, SecurityStateBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { IconClose, IconTarget } from "@/components/ui/icons";
import { StatList, StatRow } from "@/components/ui/Metric";
import { EmptyState } from "@/components/ui/States";
import { ShapeGlyph } from "@/components/graph/GraphLegend";
import { describeCompromisedBy, describeTickCompromised } from "@/lib/format";
import { incidentEdges, meshNeighbors, nodeShape, type TopologyModel } from "@/lib/graph/model";
import type { InsightsMode } from "@/lib/security/useSecurityInsights";
import { useProvenance } from "@/lib/security/useProvenance";
import type { Event, NodeView } from "@/lib/stream/reducer";
import { nodeTypeMeta, PLANE_LABEL } from "@/lib/vocabulary";

/**
 * Everything known about one node, in the order an investigation asks for it:
 * what is it → what state is it in → how did it get there → what can it reach
 * → what happened to it.
 */
export function NodeInspector({
  nodeId,
  model,
  streamNode,
  incidents,
  experimentId,
  mode = "live",
  onClose,
  onTraceFrom,
}: {
  nodeId: string;
  model: TopologyModel;
  streamNode: NodeView | null;
  incidents: Event[];
  experimentId: string;
  mode?: InsightsMode;
  onClose: () => void;
  onTraceFrom?: (nodeId: string) => void;
}) {
  const node = model.nodes.find((n) => n.id === nodeId);
  const provenance = useProvenance(experimentId, node?.nodeType === "agent" ? nodeId : null, mode);

  if (!node) {
    return (
      <EmptyState
        compact
        title="Node not in this run"
        description={`${nodeId} is not part of the current topology.`}
      />
    );
  }

  const meta = nodeTypeMeta(node.nodeType);
  const neighbors = meshNeighbors(model.edges, nodeId);
  const connections = incidentEdges(model.edges, nodeId).filter(
    (edge) => edge.edgeType !== "communicates_with" && edge.edgeType !== "trusts",
  );
  const chain = provenance.chain ?? [];
  const isAgent = node.nodeType === "agent";

  return (
    <div className="flex min-h-0 flex-col">
      <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <ShapeGlyph shape={nodeShape(node.nodeType)} className="mt-0.5 shrink-0 text-fg-subtle" />
          <div className="min-w-0">
            <p className="truncate font-mono text-sm text-fg">{node.id}</p>
            <p className="mt-0.5 text-2xs text-fg-subtle">
              {meta.label} · {PLANE_LABEL[meta.plane]}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {onTraceFrom && isAgent && (
            <Button
              size="sm"
              variant="ghost"
              title="Use as the source of an attack-path query"
              onClick={() => onTraceFrom(node.id)}
            >
              <IconTarget className="size-3.5" />
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close inspector">
            <IconClose className="size-3.5" />
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <div className="mb-3">
          <SecurityStateBadge state={node.securityState} />
        </div>

        <StatList>
          {isAgent && (
            <>
              <StatRow label="Software stack" value={String(node.attrs.software_type ?? "—")} />
              <StatRow
                label="Agent kind"
                value={node.attrs.agent_kind === "real" ? "LLM-backed" : "Simulated"}
              />
            </>
          )}
          {!isAgent && node.attrs.kind !== undefined && (
            <StatRow label="Control kind" value={String(node.attrs.kind)} />
          )}
          {isAgent && streamNode && (
            <>
              <StatRow label="Compromised by" value={describeCompromisedBy(streamNode)} />
              <StatRow label="Compromised at tick" value={describeTickCompromised(streamNode)} />
            </>
          )}
          <StatRow label="Mesh neighbours" value={neighbors.length} />
        </StatList>

        {isAgent && (
          <section className="mt-4">
            <p className="eyebrow mb-1.5">Causal trace</p>
            {provenance.loading && <p className="text-xs text-fg-subtle">Tracing…</p>}
            {!provenance.loading && chain.length <= 1 && (
              <p className="text-xs text-fg-subtle">
                {node.securityState === "healthy"
                  ? "Not compromised — nothing to trace."
                  : "No upstream source recorded: this is the seeded initial foothold, or the chain predates this session."}
              </p>
            )}
            {chain.length > 1 && (
              <>
                <p className="mb-1.5 text-2xs text-fg-subtle">
                  Backtrace to patient zero, newest first.
                </p>
                <ol className="flex flex-col">
                  {chain.map((step, index) => (
                    <li key={step} className="flex items-center gap-2 py-0.5">
                      <span
                        aria-hidden
                        className="flex size-4 shrink-0 items-center justify-center rounded-full border border-line text-[9px] text-fg-subtle"
                      >
                        {index + 1}
                      </span>
                      <span className="truncate font-mono text-2xs text-fg-muted">{step}</span>
                      {index === chain.length - 1 && (
                        <Badge severity="critical" className="ml-auto shrink-0">
                          Patient zero
                        </Badge>
                      )}
                    </li>
                  ))}
                </ol>
              </>
            )}
          </section>
        )}

        {connections.length > 0 && (
          <section className="mt-4">
            <p className="eyebrow mb-1.5">Reaches</p>
            <ul className="flex flex-col gap-1">
              {connections.slice(0, 12).map((edge) => {
                const other = edge.source === nodeId ? edge.target : edge.source;
                return (
                  <li key={`${edge.edgeType}:${other}`} className="flex items-baseline gap-2">
                    <span className="truncate font-mono text-2xs text-fg-muted">{other}</span>
                    <span aria-hidden className="min-w-2 flex-1 border-b border-dotted border-line" />
                    <span className="shrink-0 text-2xs text-fg-subtle">
                      {edge.edgeType.replace(/_/g, " ")}
                    </span>
                  </li>
                );
              })}
              {connections.length > 12 && (
                <li className="text-2xs text-fg-subtle">
                  +{connections.length - 12} more connections
                </li>
              )}
            </ul>
          </section>
        )}

        <section className="mt-4">
          <p className="eyebrow mb-1.5">Incidents</p>
          <p className="mb-1.5 text-2xs text-fg-subtle">
            Security-relevant events observed for this node in this session.
          </p>
          {incidents.length === 0 ? (
            <p className="text-xs text-fg-subtle">No incidents observed.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-line/60">
              {[...incidents].reverse().map((event) => (
                <EventRow key={event.event_id} event={event} compact />
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
