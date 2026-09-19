import { MetricTile, StatList, StatRow } from "@/components/ui/Metric";
import { formatLatency, formatPercent } from "@/lib/format";
import type { MetricsResponse } from "@/lib/api/client";
import { severityForHealth, severityForRisk, type Severity } from "@/lib/severity";

export type MetricDescriptor = {
  key: keyof MetricsResponse;
  label: string;
  definition: string;
  kind: "risk" | "health" | "count" | "latency";
};

/**
 * Every metric the backend computes, with the definition it is computed from.
 * A security number without its definition is not a claim anyone can check —
 * and the definitions here are literally `app/metrics/compute.py`'s.
 */
export const METRIC_DESCRIPTORS: readonly MetricDescriptor[] = [
  {
    key: "compromise_fraction",
    label: "Compromise fraction",
    definition: "Compromised agents ÷ all agents.",
    kind: "risk",
  },
  {
    key: "blast_radius_fraction",
    label: "Blast radius",
    definition:
      "Agents reachable from any currently-compromised node across propagation-capable edges ÷ all agents.",
    kind: "risk",
  },
  {
    key: "attack_success_rate",
    label: "Attack success rate",
    definition: "Successful compromises ÷ (successful + failed), over observed events.",
    kind: "risk",
  },
  {
    key: "false_quarantine_rate",
    label: "False-quarantine rate",
    definition:
      "Quarantines exercised without a preceding detection ÷ all quarantines — the cost of a subverted quarantine authority.",
    kind: "risk",
  },
  {
    key: "retained_utility",
    label: "Retained utility",
    definition: "Agents neither compromised nor quarantined ÷ all agents.",
    kind: "health",
  },
  {
    key: "security_plane_integrity",
    label: "Security-plane integrity",
    definition: "Healthy sentinels and security controls ÷ all of them.",
    kind: "health",
  },
  {
    key: "privileged_exposure",
    label: "Privileged exposure",
    definition: "Credential and resource nodes inside the blast radius.",
    kind: "count",
  },
  {
    key: "detection_latency",
    label: "Detection latency",
    definition: "Mean ticks from a node's compromise to the first anomaly detected on it.",
    kind: "latency",
  },
  {
    key: "containment_latency",
    label: "Containment latency",
    definition: "Mean ticks from detection to the first legitimate quarantine.",
    kind: "latency",
  },
];

export function metricSeverity(descriptor: MetricDescriptor, value: number | null): Severity {
  if (value === null) return "neutral";
  if (descriptor.kind === "risk") return severityForRisk(value);
  if (descriptor.kind === "health") return severityForHealth(value);
  if (descriptor.kind === "count") return value > 0 ? "high" : "ok";
  return "neutral";
}

export function formatMetric(descriptor: MetricDescriptor, value: number | null): string {
  if (value === null) return "—";
  if (descriptor.kind === "latency") return formatLatency(value);
  if (descriptor.kind === "count") return String(value);
  return formatPercent(value);
}

/** The four numbers that answer "how bad is it" first. */
export function PostureTiles({ metrics }: { metrics: MetricsResponse }) {
  const tiles: Array<{ descriptor: MetricDescriptor; footnote?: string }> = [
    { descriptor: METRIC_DESCRIPTORS[0] },
    { descriptor: METRIC_DESCRIPTORS[1] },
    { descriptor: METRIC_DESCRIPTORS[4] },
    { descriptor: METRIC_DESCRIPTORS[5] },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      {tiles.map(({ descriptor }) => {
        const raw = metrics[descriptor.key];
        const value = typeof raw === "number" ? raw : null;
        const severity = metricSeverity(descriptor, value);
        return (
          <MetricTile
            key={descriptor.key}
            label={descriptor.label}
            hint={descriptor.definition}
            value={formatMetric(descriptor, value)}
            severity={severity}
            fraction={value ?? 0}
          />
        );
      })}
    </div>
  );
}

/** Full metric list with definitions, for the Metrics screen and side panels. */
export function MetricsList({
  metrics,
  keys,
  withDefinitions,
}: {
  metrics: MetricsResponse;
  keys?: ReadonlyArray<keyof MetricsResponse>;
  withDefinitions?: boolean;
}) {
  const descriptors = keys
    ? METRIC_DESCRIPTORS.filter((d) => keys.includes(d.key))
    : METRIC_DESCRIPTORS;

  return (
    <StatList>
      {descriptors.map((descriptor) => {
        const raw = metrics[descriptor.key];
        const value = typeof raw === "number" ? raw : null;
        return (
          <StatRow
            key={descriptor.key}
            label={
              withDefinitions ? (
                <span className="block">
                  <span className="block text-xs text-fg-muted">{descriptor.label}</span>
                  <span className="block max-w-md text-2xs leading-4 text-fg-subtle">
                    {descriptor.definition}
                  </span>
                </span>
              ) : (
                descriptor.label
              )
            }
            hint={withDefinitions ? undefined : descriptor.definition}
            value={formatMetric(descriptor, value)}
            severity={metricSeverity(descriptor, value)}
          />
        );
      })}
    </StatList>
  );
}
