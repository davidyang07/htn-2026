"use client";

import Link from "next/link";

import { ArmStatusCard } from "@/components/insights/ArmStatusCard";
import { MetricsDeltaTable } from "@/components/insights/MetricsComparison";
import { PageHeader } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/Button";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { Disclaimer, EmptyState } from "@/components/ui/States";
import { ConfigChip } from "@/components/ui/Badge";
import { useExperiment } from "@/lib/experiment/ExperimentProvider";
import { DEFAULT_CONFIG } from "@/lib/experiment/presets";
import { useComparison } from "@/lib/comparison/useComparison";
import { configLabel } from "@/lib/vocabulary";

const SUMMARY_FIELDS = ["seed", "node_count", "detector_sensitivity", "max_ticks"] as const;

export default function DefensesPage() {
  const { control } = useExperiment();
  const { armA, armB, runComparison } = useComparison();
  const baseConfig = control.activeConfig ?? DEFAULT_CONFIG;
  const running = armA.status === "running" || armB.status === "running";
  const started = armA.status !== "idle" || armB.status !== "idle";

  return (
    <div className="flex flex-col">
      <PageHeader
        eyebrow="Compare"
        title="Defense comparison"
        description="Two independent runs of the identical configuration — same seed, same topology, same attack — with only the defense flipped. That single-variable discipline is what makes the difference attributable to the defense rather than to luck."
        actions={
          <Button variant="primary" onClick={() => runComparison(baseConfig)} disabled={running}>
            {running ? "Running both arms…" : started ? "Run again" : "Run comparison"}
          </Button>
        }
      />

      <div className="flex flex-col gap-4 p-4 lg:p-5">
        <Panel>
          <PanelHeader
            title="Configuration under test"
            description={
              control.activeConfig
                ? "Taken from the active assessment. Everything except defense_enabled is held constant across both arms."
                : "No active assessment — the default configuration will be used for both arms."
            }
            actions={
              !control.activeConfig && (
                <Link href="/" className="text-2xs font-medium text-accent hover:text-accent-hover">
                  Launch an assessment →
                </Link>
              )
            }
          />
          <div className="flex flex-wrap gap-1.5">
            {SUMMARY_FIELDS.map((field) => (
              <ConfigChip
                key={field}
                label={configLabel(field)}
                value={String(baseConfig[field])}
              />
            ))}
            {(baseConfig.active_scenarios ?? []).map((scenario) => (
              <ConfigChip key={scenario} label="scenario" value={scenario} />
            ))}
          </div>
        </Panel>

        <div className="grid gap-4 sm:grid-cols-2">
          <ArmStatusCard label="Defense off" hint="Control arm" arm={armB} />
          <ArmStatusCard label="Defense on" hint="Treatment arm" arm={armA} />
        </div>

        <Panel flush>
          <PanelHeader
            bordered
            title="Outcome"
            description="Change is measured from the undefended control to the defended arm."
          />
          {!started ? (
            <EmptyState
              title="No comparison run yet"
              description="Running the comparison launches two fresh experiments and waits for both to complete. Nothing about the currently active assessment changes."
              action={
                <Button variant="primary" size="sm" onClick={() => runComparison(baseConfig)}>
                  Run comparison
                </Button>
              }
            />
          ) : (
            <MetricsDeltaTable
              before={armB.status === "done" ? (armB.metrics ?? null) : null}
              after={armA.status === "done" ? (armA.metrics ?? null) : null}
              beforeLabel="Defense off"
              afterLabel="Defense on"
            />
          )}
        </Panel>

        <Disclaimer>
          Simulation results only — not real-world security evidence. Both arms are ordinary
          independent experiments; this is not a special dual-run mode.
        </Disclaimer>
      </div>
    </div>
  );
}
