import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { SEVERITY_BG, SEVERITY_TEXT, type Severity } from "@/lib/severity";

/**
 * The headline KPI tile. Value dominates, label sits above it small and quiet,
 * and the meter underneath carries the severity — so a screen of tiles can be
 * read at a glance by colour alone, then in detail by number.
 */
export function MetricTile({
  label,
  value,
  unit,
  hint,
  severity = "neutral",
  fraction,
  footnote,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: string;
  severity?: Severity;
  /** 0..1 — draws the severity meter. Omit for counts with no natural ceiling. */
  fraction?: number;
  footnote?: ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-surface p-3.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="eyebrow truncate" title={hint ?? label}>
          {label}
        </span>
      </div>
      <div className="flex items-baseline gap-1">
        <span
          className={cn(
            "text-2xl font-semibold tracking-tight tabular",
            severity === "neutral" ? "text-fg" : SEVERITY_TEXT[severity],
          )}
        >
          {value}
        </span>
        {unit && <span className="text-xs text-fg-subtle">{unit}</span>}
      </div>
      {fraction !== undefined && <Meter fraction={fraction} severity={severity} />}
      {footnote && <p className="text-2xs leading-4 text-fg-subtle">{footnote}</p>}
    </div>
  );
}

export function Meter({
  fraction,
  severity = "neutral",
  className,
}: {
  fraction: number;
  severity?: Severity;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(1, fraction)) * 100;
  return (
    <div
      className={cn("h-1 w-full overflow-hidden rounded-full bg-line", className)}
      role="presentation"
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-300", SEVERITY_BG[severity])}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

/**
 * Dense label/value row for the many small metric lists. Uses a definition
 * list so screen readers get the pairing, and a leader line so the eye can
 * track from a long label to its right-aligned value.
 */
export function StatRow({
  label,
  value,
  severity,
  hint,
}: {
  label: ReactNode;
  value: ReactNode;
  severity?: Severity;
  hint?: string;
}) {
  return (
    <div className="flex items-baseline gap-2 py-1" title={hint}>
      <dt className="shrink-0 text-xs text-fg-muted">{label}</dt>
      <span aria-hidden className="min-w-3 flex-1 translate-y-[-3px] border-b border-dotted border-line" />
      <dd
        className={cn(
          "shrink-0 font-mono text-xs tabular",
          severity ? SEVERITY_TEXT[severity] : "text-fg",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

export function StatList({ children, className }: { children: ReactNode; className?: string }) {
  return <dl className={cn("divide-y divide-line/60", className)}>{children}</dl>;
}

/**
 * Horizontal stacked bar showing how a population splits across security
 * states. Reads faster than four separate counts when the question is
 * "how much of the fleet is still healthy".
 */
export function StackedBar({
  segments,
  className,
}: {
  segments: ReadonlyArray<{ key: string; value: number; severity: Severity; label: string }>;
  className?: string;
}) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  if (total === 0) {
    return <div className={cn("h-2 w-full rounded-full bg-line", className)} />;
  }
  return (
    <div className={cn("flex h-2 w-full gap-px overflow-hidden rounded-full bg-line", className)}>
      {segments
        .filter((s) => s.value > 0)
        .map((s) => (
          <div
            key={s.key}
            className={cn("h-full transition-[width] duration-300", SEVERITY_BG[s.severity])}
            style={{ width: `${(s.value / total) * 100}%` }}
            title={`${s.label}: ${s.value}`}
          />
        ))}
    </div>
  );
}
