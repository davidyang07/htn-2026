import Link from "next/link";

import { cn } from "@/lib/cn";

export type StageState = "done" | "active" | "pending";

export type Stage = {
  id: string;
  label: string;
  description: string;
  href: string;
  state: StageState;
};

/**
 * The product's workflow, rendered as the thing it is: an ordered pipeline.
 *
 * A first-time viewer should be able to tell what this tool does from one
 * glance at this strip — Map → Attack → Observe → Measure → Remediate →
 * Re-test — and click straight into whichever step they are on.
 */
export function WorkflowTracker({ stages }: { stages: readonly Stage[] }) {
  return (
    <ol className="flex flex-wrap items-stretch gap-1.5">
      {stages.map((stage, index) => (
        <li key={stage.id} className="flex min-w-0 flex-1 basis-40 items-stretch">
          <Link
            href={stage.href}
            title={stage.description}
            className={cn(
              "group flex min-w-0 flex-1 flex-col gap-1 rounded-md border px-2.5 py-2 transition-colors duration-100",
              stage.state === "done" && "border-line bg-raised",
              stage.state === "active" && "border-accent-line bg-accent-soft",
              stage.state === "pending" && "border-line border-dashed bg-transparent",
            )}
          >
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden
                className={cn(
                  "flex size-4 shrink-0 items-center justify-center rounded-full text-[9px] font-semibold",
                  stage.state === "done" && "bg-ok-soft text-ok",
                  stage.state === "active" && "bg-accent text-white",
                  stage.state === "pending" && "border border-line text-fg-subtle",
                )}
              >
                {stage.state === "done" ? "✓" : index + 1}
              </span>
              <span
                className={cn(
                  "truncate text-xs font-medium",
                  stage.state === "pending" ? "text-fg-subtle" : "text-fg",
                )}
              >
                {stage.label}
              </span>
            </span>
            <span className="line-clamp-2 text-2xs leading-4 text-fg-subtle">
              {stage.description}
            </span>
          </Link>
        </li>
      ))}
    </ol>
  );
}
