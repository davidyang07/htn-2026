"use client";

import { cn } from "@/lib/cn";
import { nodeShape, type NodeShape } from "@/lib/graph/model";
import {
  SECURITY_STATE_HINT,
  SECURITY_STATE_LABEL,
  SECURITY_STATE_SEVERITY,
  SEVERITY_HEX,
  type SecurityState,
} from "@/lib/severity";
import { EDGE_LAYER_META, nodeTypeMeta, type EdgeLayer } from "@/lib/vocabulary";

const STATES: SecurityState[] = [
  "healthy",
  "suspicious",
  "compromised",
  "quarantined",
  "recovered",
];

/** Legend glyph matching the shape ring the graph draws for that node type. */
export function ShapeGlyph({
  shape,
  className,
  color = "currentColor",
}: {
  shape: NodeShape;
  className?: string;
  color?: string;
}) {
  const common = { fill: "none", stroke: color, strokeWidth: 1.3, strokeLinejoin: "round" as const };
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden className={className}>
      {shape === "circle" && <circle cx="7" cy="7" r="4.4" {...common} />}
      {shape === "square" && <rect x="2.8" y="2.8" width="8.4" height="8.4" rx="1" {...common} />}
      {shape === "diamond" && <path d="M7 2.2 11.8 7 7 11.8 2.2 7Z" {...common} />}
      {shape === "triangle" && <path d="M7 2 12 11H2Z" {...common} />}
      {shape === "hexagon" && <path d="M7 1.9 11.4 4.45v5.1L7 12.1 2.6 9.55v-5.1Z" {...common} />}
      {shape === "shield" && (
        <path d="M2.9 2.9h8.2v4.4c0 2.1-1.6 3.7-4.1 4.6-2.5-.9-4.1-2.5-4.1-4.6V2.9Z" {...common} />
      )}
    </svg>
  );
}

/**
 * The encoding key, as a single strip under the graph rather than a floating
 * card: a card large enough to hold both scales inevitably sits on top of the
 * nodes it is explaining.
 */
export function GraphLegend({
  nodeTypes,
  className,
}: {
  /** Node types actually present in this run — a legend for absent kinds is noise. */
  nodeTypes: readonly string[];
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-line bg-surface px-4 py-2",
        className,
      )}
    >
      <span className="eyebrow">State</span>
      <ul className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {STATES.map((state) => (
          <li
            key={state}
            className="flex items-center gap-1.5 text-2xs text-fg-muted"
            title={SECURITY_STATE_HINT[state]}
          >
            <span
              className="size-2 shrink-0 rounded-full"
              style={{ background: SEVERITY_HEX[SECURITY_STATE_SEVERITY[state]] }}
            />
            {SECURITY_STATE_LABEL[state]}
          </li>
        ))}
      </ul>

      <span aria-hidden className="hidden h-4 w-px bg-line sm:block" />

      <span className="eyebrow">Type</span>
      <ul className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {nodeTypes.map((type) => (
          <li
            key={type}
            className="flex items-center gap-1.5 text-2xs text-fg-muted"
            title={nodeTypeMeta(type).hint}
          >
            <ShapeGlyph shape={nodeShape(type)} className="shrink-0 text-fg-subtle" />
            {nodeTypeMeta(type).label}
          </li>
        ))}
      </ul>

      <p className="ml-auto hidden text-2xs text-fg-subtle xl:block">
        Colour is security state; shape and size are node type. LLM-backed agents render larger.
      </p>
    </div>
  );
}

export function LayerToggles({
  layers,
  onToggle,
  available,
}: {
  layers: ReadonlySet<EdgeLayer>;
  onToggle: (layer: EdgeLayer) => void;
  available: readonly EdgeLayer[];
}) {
  return (
    <div className="flex items-center gap-1" role="group" aria-label="Edge layers">
      {available.map((layer) => {
        const active = layers.has(layer);
        const meta = EDGE_LAYER_META[layer];
        return (
          <button
            key={layer}
            type="button"
            aria-pressed={active}
            title={meta.hint}
            onClick={() => onToggle(layer)}
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-2 py-1 text-2xs font-medium transition-colors duration-100",
              active
                ? "border-line-strong bg-raised text-fg"
                : "border-line bg-transparent text-fg-subtle hover:text-fg-muted",
            )}
          >
            <span
              className="h-px w-3.5 shrink-0"
              style={{ background: active ? meta.color : "#2a3040" }}
            />
            {meta.label}
          </button>
        );
      })}
    </div>
  );
}
