import { Panel, PanelHeader } from "@/components/ui/Panel";
import { EmptyState } from "@/components/ui/States";
import { cn } from "@/lib/cn";
import type { TestEvidence, TestRun } from "@/lib/runtime/testRuns";

/**
 * RED → GREEN, the one piece of evidence the user's task actually asked for.
 *
 * The same regression file, run twice: against the vulnerable module, where it
 * must fail, and against the patched one, where it must pass. A suite that was
 * always green proves nothing about a vulnerability, which is why the red run
 * is given equal billing rather than being overwritten by the green one.
 *
 * Every number here is parsed from pytest's own summary line, and the line
 * itself is printed underneath it. Nothing is counted by this component.
 */
export function TestEvidencePanel({ evidence }: { evidence: TestEvidence }) {
  if (evidence.before === null) {
    return (
      <Panel>
        <PanelHeader
          title="Regression evidence"
          description="The same suite, before the fix and after it."
        />
        <EmptyState
          compact
          title="No test run reported yet"
          description="Both runs are real pytest subprocesses; their output appears here verbatim."
        />
      </Panel>
    );
  }

  return (
    <Panel>
      <PanelHeader
        title="Regression evidence"
        description="One regression file, run against the vulnerable module and the patched one."
      />

      <div className="grid items-stretch gap-3 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
        <RunCard run={evidence.before} phase="Before fix" />
        {evidence.after ? (
          <>
            <PatchArrow />
            <RunCard run={evidence.after} phase="After fix" />
          </>
        ) : (
          <>
            <PatchArrow pending />
            <PendingCard />
          </>
        )}
      </div>

      <p className="mt-3 text-2xs leading-4 text-fg-subtle">
        Verbatim from real <span className="font-mono">pytest</span> subprocesses. The verdict
        comes from each run&rsquo;s exit code, not from its text, so a red run is reported red.
      </p>
    </Panel>
  );
}

/** Colour follows what the count *means*, not which card it sits in. */
function countClass(label: string): string {
  if (label === "passed") return "text-ok";
  if (label === "failed" || label.startsWith("error")) return "text-critical";
  return "text-fg-muted";
}

function RunCard({ run, phase }: { run: TestRun; phase: string }) {
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col gap-2 rounded-lg border p-3.5",
        run.passed ? "border-ok/35 bg-ok-soft" : "border-critical/40 bg-critical-soft",
      )}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="eyebrow">{phase}</span>
        <span
          className={cn(
            "text-2xs font-bold uppercase tracking-[0.12em]",
            run.passed ? "text-ok" : "text-critical",
          )}
        >
          {run.passed ? "Green" : "Red"}
        </span>
      </div>

      {run.counts.length > 0 ? (
        <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          {run.counts.map((count) => (
            <span key={count.label} className="flex items-baseline gap-1.5">
              <span className={cn("text-xl font-semibold tabular", countClass(count.label))}>
                {count.value}
              </span>
              <span className="text-2xs text-fg-muted">{count.label}</span>
            </span>
          ))}
        </p>
      ) : (
        // An unparseable line still has to be readable; it is not turned into
        // a number that pytest never reported.
        <p className={cn("text-sm font-medium", run.passed ? "text-ok" : "text-critical")}>
          {run.summary}
        </p>
      )}

      <p
        className="truncate border-t border-line/50 pt-2 font-mono text-2xs text-fg-subtle"
        title={run.summary}
      >
        {run.command ?? "pytest"}
      </p>
      {run.counts.length > 0 && (
        <p className="truncate font-mono text-2xs text-fg-subtle" title={run.summary}>
          {run.summary}
        </p>
      )}
    </div>
  );
}

function PatchArrow({ pending }: { pending?: boolean }) {
  return (
    <div className="flex items-center justify-center gap-2 sm:flex-col">
      <span
        aria-hidden
        className={cn(
          "text-base",
          pending ? "text-fg-subtle" : "text-fg-muted",
          "sm:rotate-0",
        )}
      >
        →
      </span>
      <span className="whitespace-nowrap text-2xs text-fg-subtle sm:[writing-mode:vertical-rl]">
        patch applied
      </span>
    </div>
  );
}

function PendingCard() {
  return (
    <div className="flex min-w-0 flex-col justify-center gap-1 rounded-lg border border-dashed border-line bg-surface p-3.5">
      <span className="eyebrow">After fix</span>
      <p className="text-xs text-fg-subtle">
        The patched run has not been recorded yet.
      </p>
    </div>
  );
}
