"use client";

import {
  formatMetric,
  METRIC_DESCRIPTORS,
  metricSeverity,
  type MetricDescriptor,
} from "@/components/insights/SecurityMetrics";
import { Td, TableWrap, Th, Tr } from "@/components/ui/Table";
import { cn } from "@/lib/cn";
import type { MetricsResponse } from "@/lib/api/client";
import { SEVERITY_TEXT } from "@/lib/severity";

/** Whether a *decrease* in this metric is an improvement. */
function lowerIsBetter(descriptor: MetricDescriptor): boolean {
  return descriptor.kind !== "health";
}

export type DeltaDirection = "better" | "worse" | "same" | "unknown";

export function deltaDirection(
  descriptor: MetricDescriptor,
  before: number | null,
  after: number | null,
): DeltaDirection {
  if (before === null || after === null) return "unknown";
  if (before === after) return "same";
  const decreased = after < before;
  return decreased === lowerIsBetter(descriptor) ? "better" : "worse";
}

function formatDelta(descriptor: MetricDescriptor, before: number | null, after: number | null) {
  if (before === null || after === null) return "—";
  const diff = after - before;
  if (diff === 0) return "no change";
  const sign = diff > 0 ? "+" : "−";
  const magnitude = Math.abs(diff);
  if (descriptor.kind === "count") return `${sign}${magnitude}`;
  if (descriptor.kind === "latency") return `${sign}${magnitude.toFixed(1)} ticks`;
  return `${sign}${Math.round(magnitude * 100)} pts`;
}

/**
 * Two metric sets side by side with an explicit direction of travel.
 *
 * Two independent lists of numbers make the reader do the subtraction — and
 * the subtraction is the entire point of a comparison, whether the arms are
 * defense on/off or before/after a fix.
 */
export function MetricsDeltaTable({
  before,
  after,
  beforeLabel,
  afterLabel,
}: {
  before: MetricsResponse | null;
  after: MetricsResponse | null;
  beforeLabel: string;
  afterLabel: string;
}) {
  return (
    <TableWrap>
      <thead>
        <tr>
          <Th className="w-1/2">Metric</Th>
          <Th className="text-right">{beforeLabel}</Th>
          <Th className="text-right">{afterLabel}</Th>
          <Th className="text-right">Change</Th>
        </tr>
      </thead>
      <tbody>
        {METRIC_DESCRIPTORS.map((descriptor) => {
          const rawBefore = before?.[descriptor.key];
          const rawAfter = after?.[descriptor.key];
          const beforeValue = typeof rawBefore === "number" ? rawBefore : null;
          const afterValue = typeof rawAfter === "number" ? rawAfter : null;
          const direction = deltaDirection(descriptor, beforeValue, afterValue);
          return (
            <Tr key={descriptor.key}>
              <Td className="text-fg">
                <span className="block text-xs text-fg">{descriptor.label}</span>
                <span className="block max-w-lg text-2xs leading-4 text-fg-subtle">
                  {descriptor.definition}
                </span>
              </Td>
              <Td className="text-right font-mono text-fg-muted">
                {before ? formatMetric(descriptor, beforeValue) : "—"}
              </Td>
              <Td
                className={cn(
                  "text-right font-mono",
                  afterValue !== null
                    ? SEVERITY_TEXT[metricSeverity(descriptor, afterValue)]
                    : "text-fg-muted",
                )}
              >
                {after ? formatMetric(descriptor, afterValue) : "—"}
              </Td>
              <Td className="text-right">
                <span
                  className={cn(
                    "font-mono text-2xs",
                    direction === "better" && "text-ok",
                    direction === "worse" && "text-critical",
                    (direction === "same" || direction === "unknown") && "text-fg-subtle",
                  )}
                >
                  {formatDelta(descriptor, beforeValue, afterValue)}
                </span>
              </Td>
            </Tr>
          );
        })}
      </tbody>
    </TableWrap>
  );
}
