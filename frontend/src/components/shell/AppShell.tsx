"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { RunContextBar } from "@/components/shell/RunContextBar";
import { isActivePath, NAV } from "@/components/shell/nav";
import { BrandMark } from "@/components/ui/icons";
import { cn } from "@/lib/cn";

/**
 * Workspace chrome: a persistent rail on the left, a run-context bar across
 * the top, and the screen itself scrolling underneath. The live WebSocket
 * lives above this in ExperimentProvider, so moving between screens never
 * interrupts a running assessment.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex h-dvh min-h-0 w-full overflow-hidden bg-canvas">
      <nav
        aria-label="Primary"
        className="hidden w-56 shrink-0 flex-col border-r border-line bg-surface lg:flex"
      >
        <Link
          href="/"
          className="flex items-center gap-2.5 px-4 py-3.5 text-fg transition-colors hover:text-accent"
        >
          <BrandMark className="shrink-0 text-accent" />
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold tracking-tight">AgentShield</span>
            <span className="block truncate text-2xs text-fg-subtle">
              Adversarial resilience
            </span>
          </span>
        </Link>

        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto border-t border-line px-2.5 py-4">
          {NAV.map((group) => (
            <div key={group.label}>
              <p className="eyebrow px-2 pb-1.5">{group.label}</p>
              <ul className="flex flex-col gap-0.5">
                {group.items.map((item) => {
                  const active = isActivePath(pathname, item.href);
                  const Icon = item.icon;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "group flex items-center gap-2.5 rounded-md px-2 py-1.5 transition-colors duration-100",
                          active
                            ? "bg-accent-soft text-fg"
                            : "text-fg-muted hover:bg-raised hover:text-fg",
                        )}
                      >
                        <Icon
                          className={cn(
                            "size-4 shrink-0",
                            active ? "text-accent" : "text-fg-subtle group-hover:text-fg-muted",
                          )}
                        />
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">
                          {item.label}
                        </span>
                        <span
                          className={cn(
                            "shrink-0 text-2xs",
                            active ? "text-accent/70" : "text-fg-subtle/70",
                          )}
                        >
                          {item.stage}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>

        <div className="border-t border-line px-4 py-3">
          <p className="text-2xs leading-4 text-fg-subtle">
            Deterministic simulation. Results are reproducible from{" "}
            <span className="font-mono">(seed, config)</span> — not real-world security evidence.
          </p>
        </div>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Archive screens are about a *persisted* run; showing the live run's
            status and transport beside a replay of a different run is the kind
            of ambiguity that makes an operator distrust the whole screen. */}
        {!pathname.startsWith("/history") && <RunContextBar />}

        {/* Below `lg` the rail is replaced by a horizontal strip, so the nav
            never eats a third of a narrow viewport. */}
        <nav
          aria-label="Primary"
          className="flex shrink-0 gap-1 overflow-x-auto border-b border-line bg-surface px-3 py-1.5 lg:hidden"
        >
          {NAV.flatMap((group) => group.items).map((item) => {
            const active = isActivePath(pathname, item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors",
                  active ? "bg-accent-soft text-fg" : "text-fg-muted hover:bg-raised",
                )}
              >
                <Icon className={cn("size-3.5", active ? "text-accent" : "text-fg-subtle")} />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}

/** Standard screen header. Every workspace screen opens with one, so titles,
 * descriptions and screen-level actions line up across the product. */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-line px-5 py-4",
        className,
      )}
    >
      <div className="min-w-0">
        {eyebrow && <p className="eyebrow mb-1">{eyebrow}</p>}
        <h1 className="text-xl font-semibold tracking-tight text-fg">{title}</h1>
        {description && (
          <p className="mt-1 max-w-3xl text-xs leading-5 text-fg-muted">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
