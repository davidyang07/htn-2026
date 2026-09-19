"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { ArmStatusCard } from "@/components/insights/ArmStatusCard";
import { MetricsDeltaTable } from "@/components/insights/MetricsComparison";
import { PageHeader } from "@/components/shell/AppShell";
import { Badge, ConfigChip } from "@/components/ui/Badge";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { Disclaimer, EmptyState, Spinner, WarningBanner } from "@/components/ui/States";
import { getExperimentDetail, type ExperimentDetail } from "@/lib/api/client";
import { useComparison } from "@/lib/comparison/useComparison";
import { shortId } from "@/lib/format";
import { configLabel } from "@/lib/vocabulary";

type DetailState =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "loaded"; detail: ExperimentDetail };

const SUMMARY_FIELDS = ["seed", "node_count", "detector_sensitivity", "max_ticks"] as const;

// Only ever sets state inside the fetch's resolution callbacks (never
// synchronously at the top of the effect), matching useReplayStream's
// pattern (react-hooks/set-state-in-effect).
function useExperimentDetailState(id: string | null): DetailState {
  const [state, setState] = useState<DetailState>({ status: "loading" });

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    getExperimentDetail(id).then(
      (detail) => {
        if (!cancelled) setState({ status: "loaded", detail });
      },
      (err: unknown) => {
        if (!cancelled)
          setState({ status: "error", error: err instanceof Error ? err.message : String(err) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [id]);

  return state;
}

/**
 * The persisted config for one arm. Arbitrary historical pairs are allowed, so
 * this is what lets a reader judge whether the pair is a fair comparison at
 * all, rather than assuming "same config, defense flipped".
 */
function ArmConfigSummary({ id, state }: { id: string; state: DetailState }) {
  if (state.status === "loading") {
    return (
      <span className="flex items-center gap-1.5 text-2xs text-fg-subtle">
        <Spinner /> Loading configuration…
      </span>
    );
  }
  if (state.status === "error") {
    return <span className="text-2xs text-critical">{state.error}</span>;
  }
  const { detail } = state;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <ConfigChip label="run" value={shortId(id)} />
      {SUMMARY_FIELDS.map((field) => (
        <ConfigChip key={field} label={configLabel(field)} value={String(detail.config[field])} />
      ))}
      <Badge severity={detail.config.defense_enabled ? "ok" : "warn"}>
        Defense {detail.config.defense_enabled ? "on" : "off"}
      </Badge>
      <Badge severity={detail.is_complete === true ? "ok" : "warn"}>
        {detail.is_complete === true ? "Complete log" : "Incomplete log"}
      </Badge>
    </div>
  );
}

function CompareContent() {
  const params = useSearchParams();
  const idA = params.get("a");
  const idB = params.get("b");
  const { armA, armB, compareHistorical } = useComparison();
  const startedFor = useRef<string | null>(null);
  const detailA = useExperimentDetailState(idA);
  const detailB = useExperimentDetailState(idB);

  useEffect(() => {
    if (!idA || !idB) return;
    const key = `${idA}:${idB}`;
    if (startedFor.current === key) return;
    startedFor.current = key;
    compareHistorical(idA, idB);
  }, [idA, idB, compareHistorical]);

  if (!idA || !idB) {
    return (
      <EmptyState
        className="h-full"
        title="Pick two runs to compare"
        description={
          <>
            Select two rows on{" "}
            <Link href="/history" className="text-accent hover:text-accent-hover">
              the runs list
            </Link>{" "}
            and choose Compare selected.
          </>
        }
      />
    );
  }

  const differsBeyondDefense =
    detailA.status === "loaded" &&
    detailB.status === "loaded" &&
    (detailA.detail.seed !== detailB.detail.seed ||
      detailA.detail.config.node_count !== detailB.detail.config.node_count ||
      detailA.detail.config.max_ticks !== detailB.detail.config.max_ticks);

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-5">
      {differsBeyondDefense && (
        <WarningBanner>
          These two runs differ in more than their defense setting — seed, size or run length is
          not held constant. Any difference below is therefore not attributable to the defense
          alone. Use <Link href="/defenses" className="underline">Defense comparison</Link> for a
          single-variable test.
        </WarningBanner>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <ArmStatusCard label="Arm A" arm={armA} hint={<ArmConfigSummary id={idA} state={detailA} />} />
        <ArmStatusCard label="Arm B" arm={armB} hint={<ArmConfigSummary id={idB} state={detailB} />} />
      </div>

      <Panel flush>
        <PanelHeader bordered title="Outcome" description="Change is measured from Arm A to Arm B." />
        <MetricsDeltaTable
          before={armA.status === "done" ? (armA.metrics ?? null) : null}
          after={armB.status === "done" ? (armB.metrics ?? null) : null}
          beforeLabel="Arm A"
          afterLabel="Arm B"
        />
      </Panel>

      <Disclaimer>
        Simulation results only — not real-world security evidence. Both arms are folded through
        the same metrics pipeline the live view uses.
      </Disclaimer>
    </div>
  );
}

export default function ComparePage() {
  return (
    <div className="flex flex-col">
      <PageHeader
        eyebrow="Archive"
        title="Compare runs"
        description="Two persisted runs, scored on identical metrics. Check the configuration of each before drawing a conclusion from the difference."
        actions={
          <Link href="/history" className="text-xs text-fg-muted transition-colors hover:text-fg">
            ← All runs
          </Link>
        }
      />
      <Suspense
        fallback={
          <div className="flex items-center gap-2 p-5 text-xs text-fg-muted">
            <Spinner /> Loading…
          </div>
        }
      >
        <CompareContent />
      </Suspense>
    </div>
  );
}
