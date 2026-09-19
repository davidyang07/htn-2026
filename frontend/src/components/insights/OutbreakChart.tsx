"use client";

import { useMemo, useState } from "react";

import { SEVERITY_HEX } from "@/lib/severity";
import type { OutbreakSample } from "@/lib/stream/useOutbreakSeries";
import { useElementSize } from "@/lib/useElementSize";
import { EmptyState } from "@/components/ui/States";

const PAD = { top: 10, right: 46, bottom: 18, left: 30 };
// A 2px surface gap separates touching stacked bands — the separation is
// negative space, never a stroke around the mark.
const BAND_GAP = 2;
const SURFACE = "#10131a";

const SERIES = [
  { key: "compromised" as const, label: "Compromised", color: SEVERITY_HEX.critical },
  { key: "quarantined" as const, label: "Quarantined", color: SEVERITY_HEX.contained },
];

/**
 * Outbreak progression: how much of the fleet the attacker holds, and how much
 * the defense has contained, tick by tick.
 *
 * Only two bands are drawn. The plot area *is* the fleet, so healthy agents are
 * the remaining negative space — a third grey band would be the largest,
 * loudest mark on a chart whose subject is the other two.
 */
export function OutbreakChart({
  series,
  maxTicks,
  emptyDescription = "The outbreak curve builds as the simulation ticks.",
}: {
  series: OutbreakSample[];
  maxTicks: number;
  /** Why there is no curve — a finished run reconnected to after a reload has
   * no live samples, which is a different situation from "not started yet". */
  emptyDescription?: string;
}) {
  const [ref, size] = useElementSize<HTMLDivElement>();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const total = series.length > 0 ? series[series.length - 1].total : 0;
  const innerWidth = Math.max(0, size.width - PAD.left - PAD.right);
  const innerHeight = Math.max(0, size.height - PAD.top - PAD.bottom);
  const lastTick = series.length > 0 ? series[series.length - 1].tick : 0;
  // The axis grows with the run rather than reserving the full configured
  // length up front — a run three ticks into a 200-tick budget would otherwise
  // render as a sliver in the corner. The axis label still names the budget.
  const tickSpan = Math.max(lastTick, 8);

  const geometry = useMemo(() => {
    if (series.length === 0 || innerWidth <= 0 || innerHeight <= 0 || total === 0) return null;
    const xOf = (tick: number) => PAD.left + (tick / tickSpan) * innerWidth;
    const yOf = (value: number) => PAD.top + innerHeight - (value / total) * innerHeight;

    const points = series.map((sample) => ({
      sample,
      x: xOf(sample.tick),
      yCompromised: yOf(sample.compromised),
      yStacked: yOf(sample.compromised + sample.quarantined),
    }));

    const baseline = PAD.top + innerHeight;
    const compromisedPath = area(
      points.map((p) => [p.x, Math.min(baseline, p.yCompromised + BAND_GAP / 2)] as const),
      baseline,
    );
    const quarantinedPath = band(
      points.map(
        (p) =>
          [p.x, p.yStacked + BAND_GAP / 2, Math.max(p.yStacked, p.yCompromised - BAND_GAP / 2)] as const,
      ),
    );
    return { points, compromisedPath, quarantinedPath, baseline, xOf, yOf };
  }, [series, innerWidth, innerHeight, total, tickSpan]);

  if (series.length === 0 || total === 0) {
    return (
      <div ref={ref} className="size-full">
        <EmptyState compact title="No progression to plot" description={emptyDescription} />
      </div>
    );
  }

  const hovered = hoverIndex !== null ? geometry?.points[hoverIndex] : undefined;
  const last = series[series.length - 1];

  return (
    <div ref={ref} className="relative size-full">
      {geometry && size.width > 0 && (
        <svg
          width={size.width}
          height={size.height}
          role="img"
          aria-label="Compromised and quarantined agents over simulated time"
          onPointerLeave={() => setHoverIndex(null)}
          onPointerMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const x = e.clientX - rect.left;
            // Snap to the nearest sample so the reader aims at a tick, never
            // at a 2px line.
            let nearest = 0;
            let best = Infinity;
            geometry.points.forEach((point, index) => {
              const distance = Math.abs(point.x - x);
              if (distance < best) {
                best = distance;
                nearest = index;
              }
            });
            setHoverIndex(nearest);
          }}
        >
          {[0.25, 0.5, 0.75, 1].map((fraction) => (
            <line
              key={fraction}
              x1={PAD.left}
              x2={PAD.left + innerWidth}
              y1={PAD.top + innerHeight * (1 - fraction)}
              y2={PAD.top + innerHeight * (1 - fraction)}
              stroke="#1c222c"
              strokeWidth="1"
            />
          ))}

          <path d={geometry.compromisedPath} fill={SEVERITY_HEX.critical} fillOpacity="0.85" />
          <path d={geometry.quarantinedPath} fill={SEVERITY_HEX.contained} fillOpacity="0.85" />

          {hovered && (
            <>
              <line
                x1={hovered.x}
                x2={hovered.x}
                y1={PAD.top}
                y2={geometry.baseline}
                stroke="#4d5b73"
                strokeWidth="1"
              />
              <circle
                cx={hovered.x}
                cy={hovered.yCompromised}
                r="3.5"
                fill={SEVERITY_HEX.critical}
                stroke={SURFACE}
                strokeWidth="2"
              />
              <circle
                cx={hovered.x}
                cy={hovered.yStacked}
                r="3.5"
                fill={SEVERITY_HEX.contained}
                stroke={SURFACE}
                strokeWidth="2"
              />
            </>
          )}

          <text x={PAD.left - 6} y={PAD.top + 4} textAnchor="end" className="fill-fg-subtle text-[9px]">
            {total}
          </text>
          <text
            x={PAD.left - 6}
            y={geometry.baseline}
            textAnchor="end"
            className="fill-fg-subtle text-[9px]"
          >
            0
          </text>
          <text
            x={PAD.left + innerWidth}
            y={size.height - 4}
            textAnchor="end"
            className="fill-fg-subtle text-[9px]"
          >
            tick {lastTick} of {maxTicks}
          </text>

          {/* Direct end-labels: the current value of each band, on the band. */}
          {last.compromised > 0 && (
            <text
              x={geometry.points[geometry.points.length - 1].x + 6}
              y={geometry.yOf(last.compromised / 2)}
              className="fill-fg-muted text-[10px]"
              dominantBaseline="middle"
            >
              {last.compromised}
            </text>
          )}
          {last.quarantined > 0 && (
            <text
              x={geometry.points[geometry.points.length - 1].x + 6}
              y={geometry.yOf(last.compromised + last.quarantined / 2)}
              className="fill-fg-muted text-[10px]"
              dominantBaseline="middle"
            >
              {last.quarantined}
            </text>
          )}
        </svg>
      )}

      {hovered && (
        <div
          className="pointer-events-none absolute top-2 rounded-md border border-line bg-overlay px-2 py-1.5 shadow-pop"
          style={{
            left: Math.min(Math.max(hovered.x - 60, 4), Math.max(4, size.width - 130)),
          }}
        >
          <p className="mb-1 font-mono text-2xs text-fg-subtle">tick {hovered.sample.tick}</p>
          {SERIES.map((s) => (
            <p key={s.key} className="flex items-baseline gap-2 text-2xs">
              <span
                aria-hidden
                className="h-0.5 w-3 shrink-0 rounded-full"
                style={{ background: s.color }}
              />
              <span className="font-mono tabular font-medium text-fg">
                {hovered.sample[s.key]}
              </span>
              <span className="text-fg-subtle">{s.label}</span>
            </p>
          ))}
          <p className="mt-0.5 flex items-baseline gap-2 text-2xs">
            <span aria-hidden className="h-0.5 w-3 shrink-0 rounded-full bg-line-strong" />
            <span className="font-mono tabular font-medium text-fg">{hovered.sample.healthy}</span>
            <span className="text-fg-subtle">Healthy</span>
          </p>
        </div>
      )}

      {/* Reachable without hovering, and the accessible fallback for the plot. */}
      <table className="sr-only">
        <caption>Agents by security state per simulated tick</caption>
        <thead>
          <tr>
            <th scope="col">Tick</th>
            <th scope="col">Compromised</th>
            <th scope="col">Quarantined</th>
            <th scope="col">Healthy</th>
          </tr>
        </thead>
        <tbody>
          {series.map((sample) => (
            <tr key={sample.tick}>
              <td>{sample.tick}</td>
              <td>{sample.compromised}</td>
              <td>{sample.quarantined}</td>
              <td>{sample.healthy}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function OutbreakLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {SERIES.map((s) => (
        <span key={s.key} className="flex items-center gap-1.5 text-2xs text-fg-muted">
          <span
            aria-hidden
            className="size-2 shrink-0 rounded-xs"
            style={{ background: s.color }}
          />
          {s.label}
        </span>
      ))}
      <span className="flex items-center gap-1.5 text-2xs text-fg-subtle">
        <span aria-hidden className="size-2 shrink-0 rounded-xs border border-line-strong" />
        Remaining area is healthy
      </span>
    </div>
  );
}

/** Area from a top edge down to a flat baseline. */
function area(points: ReadonlyArray<readonly [number, number]>, baseline: number): string {
  if (points.length === 0) return "";
  const top = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${round(x)} ${round(y)}`).join(" ");
  const first = points[0][0];
  const lastX = points[points.length - 1][0];
  return `${top} L${round(lastX)} ${round(baseline)} L${round(first)} ${round(baseline)} Z`;
}

/** Ribbon between an upper and lower edge, given as [x, yTop, yBottom]. */
function band(points: ReadonlyArray<readonly [number, number, number]>): string {
  if (points.length === 0) return "";
  const top = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${round(x)} ${round(y)}`).join(" ");
  const bottom = [...points]
    .reverse()
    .map(([x, , y]) => `L${round(x)} ${round(y)}`)
    .join(" ");
  return `${top} ${bottom} Z`;
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}
