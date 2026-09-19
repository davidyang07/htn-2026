import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * Empty state. Always says what would fill this space and how to get there —
 * a bare "no data" is the single fastest way to make a product feel unfinished.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  compact,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "gap-1.5 px-4 py-6" : "gap-2 px-6 py-12",
        className,
      )}
    >
      {icon && <div className="mb-1 text-fg-subtle">{icon}</div>}
      <p className={cn("font-medium text-fg-muted", compact ? "text-xs" : "text-sm")}>{title}</p>
      {description && (
        <p className="max-w-sm text-xs leading-5 text-fg-subtle">{description}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  detail,
  action,
  className,
}: {
  title?: string;
  detail?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col gap-1.5 rounded-md border border-critical/30 bg-critical-soft px-3 py-2.5",
        className,
      )}
    >
      <p className="text-xs font-medium text-critical">{title}</p>
      {detail && <p className="break-words font-mono text-2xs leading-4 text-critical/80">{detail}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

export function WarningBanner({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-2.5 rounded-md border border-warn/30 bg-warn-soft px-3 py-2.5 text-xs leading-5 text-warn",
        className,
      )}
    >
      <span aria-hidden className="mt-[3px] size-1.5 shrink-0 rounded-full bg-warn" />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** Non-blocking caveat used wherever simulated results could be mistaken for
 * real-world evidence. Quiet by design — it must not compete with the data. */
export function Disclaimer({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-start gap-2 text-2xs leading-4 text-fg-subtle">
      <span aria-hidden className="mt-[5px] size-1 shrink-0 rounded-full bg-fg-subtle" />
      <span>{children}</span>
    </p>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn("relative overflow-hidden rounded-sm bg-raised", className)}>
      <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/[0.04] to-transparent motion-safe:[animation:shimmer_1.6s_infinite]" />
    </div>
  );
}

export function StatListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2.5 py-1">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center justify-between gap-4">
          <Skeleton className="h-3 w-28" />
          <Skeleton className="h-3 w-10" />
        </div>
      ))}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn(
        "inline-block size-3.5 animate-spin rounded-full border-[1.5px] border-line-strong border-t-accent",
        className,
      )}
    />
  );
}
