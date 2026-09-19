"use client";

import type { ReactNode } from "react";

import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { ErrorState, Spinner } from "@/components/ui/States";
import type { ArmState } from "@/lib/comparison/useComparison";

/**
 * One arm of a two-arm comparison: what it is, whether it finished, and any
 * caveat attached to trusting its numbers. The numbers themselves live in the
 * delta table, so the two arms are always read against each other rather than
 * side by side.
 */
export function ArmStatusCard({
  label,
  hint,
  arm,
  children,
}: {
  label: string;
  hint?: ReactNode;
  arm: ArmState;
  children?: ReactNode;
}) {
  return (
    <Panel>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-medium text-fg">{label}</h3>
          {hint && <div className="mt-0.5 text-2xs text-fg-subtle">{hint}</div>}
        </div>
        {arm.status === "running" && (
          <span className="flex shrink-0 items-center gap-1.5 text-2xs text-fg-muted">
            <Spinner /> Running
          </span>
        )}
        {arm.status === "done" && <Badge severity="ok">Complete</Badge>}
        {arm.status === "error" && <Badge severity="critical">Failed</Badge>}
        {arm.status === "idle" && <Badge severity="neutral">Not run</Badge>}
      </div>

      {arm.status === "error" && (
        <ErrorState className="mt-3" title="Arm failed" detail={arm.error} />
      )}

      {arm.status === "done" && arm.incomplete && (
        <p className="mt-3 text-2xs leading-4 text-warn">
          This run&apos;s persisted log is marked incomplete — its metrics reflect only what was
          actually recorded, and should not be read as a final result.
        </p>
      )}

      {children && <div className="mt-3">{children}</div>}
    </Panel>
  );
}
