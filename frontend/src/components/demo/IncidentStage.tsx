import { Fragment } from "react";

import { WorkerNode } from "@/components/demo/WorkerNode";
import { EmptyState } from "@/components/ui/States";
import { cn } from "@/lib/cn";
import type { ProvenanceIndex } from "@/lib/runtime/provenance";
import type { Stage, StageColumn } from "@/lib/runtime/stage";

/**
 * The incident stage: the swarm drawn as the chain of work it actually is.
 *
 * Left to right is the handoff order. A replacement sits directly beneath the
 * worker it took over from, in the same column, joined by a reassignment drop
 * — so "the chain broke here and was routed around" is one shape rather than
 * something to infer from five badges.
 */
export function IncidentStage({
  stage,
  provenance,
}: {
  stage: Stage;
  provenance: ProvenanceIndex;
}) {
  if (stage.columns.length === 0) {
    return (
      <EmptyState
        className="rounded-lg border border-line bg-surface py-14"
        title="No workers registered yet"
        description="The team appears here the moment the swarm registers it."
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <div className="flex min-w-max items-stretch gap-0 p-5">
        {stage.columns.map((column, index) => (
          <Fragment key={column.column}>
            {index > 0 && <HandoffArrow broken={brokenBefore(stage, column)} />}
            <Column column={column} stage={stage} provenance={provenance} />
          </Fragment>
        ))}
      </div>
    </div>
  );
}

/**
 * Whether the handoff *into* this column came from a quarantined worker.
 *
 * The arrow between two columns is drawn interrupted in exactly that case:
 * the output the next worker would have consumed was never accepted. It is
 * derived from state, never decorative.
 */
function brokenBefore(stage: Stage, column: StageColumn): boolean {
  const previous = stage.columns.find((c) => c.column === column.column - 1);
  if (!previous) return false;
  return previous.nodes.some((node) => node.securityState === "quarantined");
}

function Column({
  column,
  stage,
  provenance,
}: {
  column: StageColumn;
  stage: Stage;
  provenance: ProvenanceIndex;
}) {
  return (
    <div className="flex w-[15rem] shrink-0 flex-col gap-0">
      {column.nodes.map((node, index) => (
        <Fragment key={node.id}>
          {index > 0 && (
            <ReassignmentDrop
              active={stage.reassignments.get(column.nodes[index - 1]!.id) === node.id}
            />
          )}
          <WorkerNode node={node} provenance={provenance.byWorker.get(node.id) ?? null} />
        </Fragment>
      ))}
    </div>
  );
}

/** Horizontal handoff between two columns. Interrupted when it was refused. */
function HandoffArrow({ broken }: { broken: boolean }) {
  return (
    <div
      aria-hidden
      className="flex w-10 shrink-0 items-center justify-center self-start pt-9"
    >
      <svg width="40" height="12" viewBox="0 0 40 12" fill="none" className="overflow-visible">
        <path
          d={broken ? "M2 6h11M27 6h9" : "M2 6h32"}
          stroke="currentColor"
          strokeWidth="1.25"
          strokeLinecap="round"
          className={broken ? "text-critical/70" : "text-line-strong"}
          strokeDasharray={broken ? "2 3" : undefined}
        />
        <path
          d="m32 2 4 4-4 4"
          stroke="currentColor"
          strokeWidth="1.25"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={broken ? "text-critical/70" : "text-line-strong"}
        />
        {broken && (
          <path
            d="m16 2 8 8M24 2l-8 8"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
            className="text-critical"
          />
        )}
      </svg>
    </div>
  );
}

/** Vertical drop from a quarantined worker to the one that took its task. */
function ReassignmentDrop({ active }: { active: boolean }) {
  return (
    <div className="flex items-center gap-2 py-1.5 pl-4">
      <svg
        aria-hidden
        width="10"
        height="26"
        viewBox="0 0 10 26"
        fill="none"
        className={cn("shrink-0", active ? "text-contained" : "text-line-strong")}
      >
        <path
          d="M5 1v18"
          stroke="currentColor"
          strokeWidth="1.25"
          strokeLinecap="round"
          strokeDasharray="2 3"
        />
        <path
          d="m1.5 16 3.5 4 3.5-4"
          stroke="currentColor"
          strokeWidth="1.25"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span
        className={cn(
          "text-2xs font-medium",
          active ? "text-contained" : "text-fg-subtle",
        )}
      >
        task reassigned
      </span>
    </div>
  );
}
