import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * One beat of the demo's story.
 *
 * /demo is not a dashboard of co-equal panels — it is a single narrative a
 * judge reads top to bottom, and the ordinal is the whole point: *what is the
 * team*, *what went wrong*, *how it recovered*, *did the job still get done*.
 * Sections are separated by space and a step marker rather than by another
 * border, so the panels inside them keep the only hairlines on the screen.
 */
export function Section({
  step,
  title,
  description,
  actions,
  children,
  className,
}: {
  /** Two-digit beat number. Purely ordinal — it never encodes state. */
  step: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("flex min-w-0 flex-col gap-3", className)}>
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span
          aria-hidden
          className="font-mono text-2xs font-medium tabular text-fg-subtle/60"
        >
          {step}
        </span>
        <h2 className="text-base font-semibold tracking-tight text-fg">{title}</h2>
        {description && (
          <p className="min-w-0 flex-1 text-xs text-fg-subtle">{description}</p>
        )}
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </header>
      {children}
    </section>
  );
}
