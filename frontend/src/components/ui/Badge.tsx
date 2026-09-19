import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import {
  RUN_STATUS_LABEL,
  RUN_STATUS_SEVERITY,
  SECURITY_STATE_LABEL,
  SECURITY_STATE_SEVERITY,
  SEVERITY_BG,
  SEVERITY_CHIP,
  type RunStatus,
  type SecurityState,
  type Severity,
} from "@/lib/severity";

export function Badge({
  severity = "neutral",
  children,
  className,
  title,
}: {
  severity?: Severity;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm px-1.5 py-0.5 text-2xs font-medium ring-1 ring-inset",
        SEVERITY_CHIP[severity],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function SeverityDot({
  severity,
  pulse,
  className,
}: {
  severity: Severity;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("relative inline-flex size-1.5 shrink-0", className)}>
      <span className={cn("size-1.5 rounded-full", SEVERITY_BG[severity])} />
      {pulse && (
        <span
          className={cn(
            "absolute inset-0 rounded-full opacity-60",
            SEVERITY_BG[severity],
            "motion-safe:animate-ping",
          )}
        />
      )}
    </span>
  );
}

export function SecurityStateBadge({ state }: { state: SecurityState }) {
  const severity = SECURITY_STATE_SEVERITY[state];
  return (
    <Badge severity={severity}>
      <SeverityDot severity={severity} />
      {SECURITY_STATE_LABEL[state]}
    </Badge>
  );
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const severity = RUN_STATUS_SEVERITY[status];
  return (
    <Badge severity={severity}>
      <SeverityDot severity={severity} pulse={status === "running"} />
      {RUN_STATUS_LABEL[status]}
    </Badge>
  );
}

/** Compact key/value chip used for run configuration summaries in the top bar. */
export function ConfigChip({ label, value }: { label: string; value: ReactNode }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 rounded-sm border border-line bg-raised px-1.5 py-0.5">
      <span className="text-2xs text-fg-subtle">{label}</span>
      <span className="font-mono text-2xs text-fg">{value}</span>
    </span>
  );
}
