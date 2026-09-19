"use client";

import { useMemo } from "react";

import { OutbreakChart, OutbreakLegend } from "@/components/insights/OutbreakChart";
import { FleetBreakdown, ObservedCountersPanel } from "@/components/insights/Panels";
import { MetricsList, PostureTiles } from "@/components/insights/SecurityMetrics";
import { PageHeader } from "@/components/shell/AppShell";
import { RequiresRun } from "@/components/shell/RequiresRun";
import { ConfigChip } from "@/components/ui/Badge";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { Disclaimer, ErrorState, StatListSkeleton } from "@/components/ui/States";
import { useExperiment } from "@/lib/experiment/ExperimentProvider";
import { useSecurityInsights } from "@/lib/security/useSecurityInsights";
import { selectMetrics } from "@/lib/stream/reducer";
import { liveLogGapHint } from "@/lib/stream/sessionScope";
import { useOutbreakSeries } from "@/lib/stream/useOutbreakSeries";
import { configLabel } from "@/lib/vocabulary";

// Config fields worth restating next to the numbers they explain — the run's
// reproducibility surface, not the whole model.
const PROVENANCE_FIELDS = [
  "seed",
  "node_count",
  "edge_density",
  "software_type_count",
  "p_same",
  "p_cross",
  "detector_sensitivity",
  "defense_enabled",
  "max_ticks",
] as const;

export default function MetricsPage() {
  return (
    <RequiresRun
      title="Nothing to measure yet"
      description="Security and utility metrics are computed from a running or completed assessment."
    >
      {(experimentId) => <MetricsContent experimentId={experimentId} />}
    </RequiresRun>
  );
}

function MetricsContent({ experimentId }: { experimentId: string }) {
  const { control, stream } = useExperiment();
  const insights = useSecurityInsights(experimentId);
  const series = useOutbreakSeries(stream);
  const streamMetrics = useMemo(() => selectMetrics(stream), [stream]);
  const config = control.activeConfig;

  return (
    <div className="flex flex-col">
      <PageHeader
        eyebrow="Measure"
        title="Security & utility metrics"
        description="Security is only meaningful against the utility it costs. Every definition below is the one the backend computes — quarantining the whole fleet scores perfectly on compromise and terribly on retained utility."
      />

      <div className="flex flex-col gap-4 p-4 lg:p-5">
        {insights.error && (
          <ErrorState title="Could not load metrics" detail={insights.error} />
        )}

        {insights.metrics ? (
          <PostureTiles metrics={insights.metrics} />
        ) : (
          <Panel>
            <StatListSkeleton rows={2} />
          </Panel>
        )}

        <div className="grid gap-4 xl:grid-cols-3">
          <Panel className="xl:col-span-2" flush>
            <PanelHeader
              bordered
              title="Outbreak progression"
              description="Per simulated tick."
              actions={<OutbreakLegend />}
            />
            <div className="h-64 p-2">
              <OutbreakChart
                series={series}
                maxTicks={config?.max_ticks ?? 200}
                emptyDescription={
                  liveLogGapHint(control.status, series.length > 0) ??
                  "The outbreak curve builds as the simulation ticks."
                }
              />
            </div>
          </Panel>

          <Panel>
            <PanelHeader title="Fleet" />
            <FleetBreakdown metrics={streamMetrics} />
            <div className="mt-4 border-t border-line pt-3">
              <ObservedCountersPanel metrics={streamMetrics} />
            </div>
          </Panel>
        </div>

        <Panel>
          <PanelHeader
            title="All metrics"
            description="Computed on demand from the run's world state, security graph and event log."
          />
          {insights.metrics ? (
            <MetricsList metrics={insights.metrics} withDefinitions />
          ) : (
            <StatListSkeleton rows={9} />
          )}
          <div className="mt-3 flex flex-col gap-2 border-t border-line pt-3">
            <Disclaimer>
              Attack success rate, false-quarantine rate and both latencies are computed over the
              live event buffer, which is bounded — a long run&apos;s earliest events may have aged
              out. Replaying a persisted run computes them over its complete log.
            </Disclaimer>
          </div>
        </Panel>

        {config && (
          <Panel>
            <PanelHeader
              title="Run provenance"
              description="The exact configuration these numbers came from. Re-running with this seed and config reproduces them byte for byte."
            />
            <div className="flex flex-wrap gap-1.5">
              {PROVENANCE_FIELDS.map((field) => (
                <ConfigChip
                  key={field}
                  label={configLabel(field)}
                  value={String(config[field])}
                />
              ))}
              {(config.active_scenarios ?? []).map((scenario) => (
                <ConfigChip key={scenario} label="scenario" value={scenario} />
              ))}
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}
