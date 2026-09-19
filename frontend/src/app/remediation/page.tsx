"use client";

import { FindingsList } from "@/components/insights/FindingsList";
import { MetricsDeltaTable } from "@/components/insights/MetricsComparison";
import { PageHeader } from "@/components/shell/AppShell";
import { RequiresRun } from "@/components/shell/RequiresRun";
import { Badge } from "@/components/ui/Badge";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import {
  Disclaimer,
  EmptyState,
  ErrorState,
  Spinner,
  StatListSkeleton,
} from "@/components/ui/States";
import { useExperiment } from "@/lib/experiment/ExperimentProvider";
import { formatConfigDiff } from "@/lib/format";
import { useFixTrial } from "@/lib/remediation/useFixTrial";
import { useSecurityInsights } from "@/lib/security/useSecurityInsights";

export default function RemediationPage() {
  return (
    <RequiresRun
      title="No findings without a run"
      description="Remediation recommendations are derived from a run's security graph and metrics. Launch an assessment first."
    >
      {(experimentId) => <RemediationContent experimentId={experimentId} />}
    </RequiresRun>
  );
}

function RemediationContent({ experimentId }: { experimentId: string }) {
  const { control } = useExperiment();
  const insights = useSecurityInsights(experimentId);
  const trial = useFixTrial();
  const config = control.activeConfig;

  return (
    <div className="flex flex-col">
      <PageHeader
        eyebrow="Remediate · Re-test"
        title="Remediation"
        description="Deterministic, rule-based recommendations — no model in the loop. Each one is a concrete configuration change with a causal mechanism behind it, and each can be re-tested here against the run it came from."
      />

      <div className="flex flex-col gap-4 p-4 lg:p-5">
        {insights.error && (
          <ErrorState title="Could not load remediation findings" detail={insights.error} />
        )}

        <Panel>
          <PanelHeader
            title="Findings"
            description="Generated from this run's compromise fraction and security-plane integrity."
            actions={
              insights.remediation && (
                <Badge
                  severity={
                    insights.remediation.recommendations.length > 0 ? "warn" : "ok"
                  }
                >
                  {insights.remediation.recommendations.length} finding
                  {insights.remediation.recommendations.length === 1 ? "" : "s"}
                </Badge>
              )
            }
          />
          {insights.remediation ? (
            <FindingsList
              recommendations={insights.remediation.recommendations}
              baseConfig={config ?? null}
              validatingKey={trial.running ? trial.diffKey : null}
              disabled={trial.running || !config}
              onValidate={(diff) => {
                if (config) trial.validate(config, diff);
              }}
            />
          ) : (
            <StatListSkeleton rows={3} />
          )}
        </Panel>

        <Panel flush>
          <PanelHeader
            bordered
            title="Fix validation"
            description="Before and after, both run to completion from the same seed."
            actions={
              trial.running ? (
                <span className="flex items-center gap-1.5 text-2xs text-fg-muted">
                  <Spinner /> Running two experiments
                </span>
              ) : trial.diffKey ? (
                <span className="font-mono text-2xs text-fg-subtle">
                  {formatConfigDiff(JSON.parse(trial.diffKey) as Record<string, unknown>)}
                </span>
              ) : null
            }
          />

          {!trial.diffKey ? (
            <EmptyState
              title="No fix validated yet"
              description="Choose a finding above and select “Validate fix”. The current configuration and the patched configuration are each run to completion, then compared on every metric — the same evidence standard the defense comparison uses."
            />
          ) : (
            <>
              {trial.before.status === "error" && (
                <ErrorState
                  className="m-4"
                  title="Baseline arm failed"
                  detail={trial.before.error}
                />
              )}
              {trial.after.status === "error" && (
                <ErrorState
                  className="m-4"
                  title="Remediated arm failed"
                  detail={trial.after.error}
                />
              )}
              <MetricsDeltaTable
                before={trial.before.status === "done" ? trial.before.metrics : null}
                after={trial.after.status === "done" ? trial.after.metrics : null}
                beforeLabel="Before fix"
                afterLabel="After fix"
              />
            </>
          )}
        </Panel>

        <Disclaimer>
          A validated fix is evidence about this simulated configuration under this seed, not a
          guarantee about a deployed system. Re-run with several seeds before treating an
          improvement as robust.
        </Disclaimer>
      </div>
    </div>
  );
}
