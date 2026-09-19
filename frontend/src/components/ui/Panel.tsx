import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * The one container in the system. Everything that groups content is a Panel
 * — no ad-hoc bordered divs — so corner radius, hairline colour and internal
 * padding rhythm stay identical across every screen.
 */
export function Panel({
  children,
  className,
  flush,
}: {
  children: ReactNode;
  className?: string;
  /** Drop the panel's own padding, for tables and graphs that bleed to the edge. */
  flush?: boolean;
}) {
  return (
    <section
      className={cn(
        "flex min-w-0 flex-col rounded-lg border border-line bg-surface shadow-panel",
        !flush && "p-4",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function PanelHeader({
  title,
  description,
  actions,
  className,
  /** Adds the divider + padding a flush panel needs around its header. */
  bordered,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
  bordered?: boolean;
}) {
  return (
    <header
      className={cn(
        "flex flex-wrap items-start justify-between gap-x-4 gap-y-2",
        bordered ? "border-b border-line px-4 py-3" : "mb-3",
        className,
      )}
    >
      <div className="min-w-0">
        <h2 className="truncate text-sm font-medium text-fg">{title}</h2>
        {description && <p className="mt-0.5 text-xs text-fg-subtle">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
}

/** Section divider inside a panel, for grouping without nesting more borders. */
export function PanelDivider({ label }: { label?: string }) {
  if (!label) return <hr className="my-4 border-line" />;
  return (
    <div className="mb-3 mt-5 flex items-center gap-3 first:mt-0">
      <span className="eyebrow shrink-0">{label}</span>
      <hr className="min-w-0 flex-1 border-line" />
    </div>
  );
}
