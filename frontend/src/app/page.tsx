"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { EventFeed } from "@/components/activity/EventFeed";
import { FindingsList } from "@/components/insights/FindingsList";
import {
  AttackSurfacePanel,
  CriticalNodesPanel,
  FleetBreakdown,
  ObservedCountersPanel,
} from "@/components/insights/Panels";
import { OutbreakChart, OutbreakLegend } from "@/components/insights/OutbreakChart";
import { PostureTiles } from "@/components/insights/SecurityMetrics";
import { WorkflowTracker, type Stage } from "@/components/insights/WorkflowTracker";
import { RunConfigurator } from "@/components/run/RunConfigurator";
import { PageHeader } from "@/components/shell/AppShell";
import { Badge } from "@/components/ui/Badge";
import { Button, ButtonLink } from "@/components/ui/Button";
import { BrandMark } from "@/components/ui/icons";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { Disclaimer, ErrorState, Spinner, StatListSkeleton } from "@/components/ui/States";
import { useExperiment } from "@/lib/experiment/ExperimentProvider";
import { DEFAULT_CONFIG } from "@/lib/experiment/presets";
import { shortId } from "@/lib/format";
import { useSecurityInsights } from "@/lib/security/useSecurityInsights";
import { selectMetrics } from "@/lib/stream/reducer";
import { liveLogGapHint } from "@/lib/stream/sessionScope";
import { useOutbreakSeries } from "@/lib/stream/useOutbreakSeries";
import { scenarioMeta } from "@/lib/vocabulary";

export default function OverviewPage() {
  const { control, stream, canStart, start, hydrating } = useExperiment();
  const insights = useSecurityInsights(control.experimentId);
  const series = useOutbreakSeries(stream);
  const streamMetrics = useMemo(() => selectMetrics(stream), [stream]);
  const [configuring, setConfiguring] = useState(false);

  if (hydrating) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-xs text-fg-muted">
        <Spinner /> Restoring session…
      </div>
    );
  }

  const config = control.activeConfig;
  const hasRun = Boolean(control.experimentId && config);
  const showConfigurator = !hasRun || configuring;

  const stages = buildStages({
    hasRun,
    observedEvents: stream.recentEvents.length,
    compromised: streamMetrics.compromised,
    hasMetrics: insights.metrics !== null,
    findings: insights.remediation?.recommendations.length ?? 0,
  });

  return (
    <div className="flex flex-col">
      {hasRun ? (
        <PageHeader
          eyebrow="Assessment overview"
          title="Security posture"
          description={
            <>
              Live posture for run{" "}
              <span className="font-mono text-fg-muted">{shortId(control.experimentId!)}</span>.
              Every number below is computed from this run&apos;s deterministic event log.
            </>
          }
          actions={
            <>
              {config && (
                <div className="hidden flex-wrap gap-1 md:flex">
                  {(config.active_scenarios ?? []).map((scenario) => (
                    <Badge key={scenario} severity="neutral">
                      {scenarioMeta(scenario).label}
                    </Badge>
                  ))}
                </div>
              )}
              <Button
                onClick={() => setConfiguring((v) => !v)}
                disabled={!canStart && !configuring}
                title={
                  canStart
                    ? "Configure and launch a new assessment"
                    : "Finish or stop the current run first"
                }
              >
                {configuring ? "Hide configuration" : "New assessment"}
              </Button>
            </>
          }
        />
      ) : (
        <LaunchHero />
      )}

      <div className="flex flex-col gap-4 p-4 lg:p-5">
        <section>
          <h2 className="eyebrow mb-2">Assessment workflow</h2>
          <WorkflowTracker stages={stages} />
        </section>

        {showConfigurator && (
          <RunConfigurator
            disabled={!canStart}
            initialConfig={config ?? DEFAULT_CONFIG}
            onStart={(next) => {
              setConfiguring(false);
              start(next);
            }}
          />
        )}

        {hasRun && (
          <>
            {insights.error && (
              <ErrorState title="Could not load derived security data" detail={insights.error} />
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
                  description="Agents held by the attacker, and agents the defense has contained, per simulated tick."
                  actions={<OutbreakLegend />}
                />
                <div className="h-56 p-2">
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
                <PanelHeader title="Fleet" description="Current split across security states." />
                <FleetBreakdown metrics={streamMetrics} />
                <div className="mt-4 border-t border-line pt-3">
                  <ObservedCountersPanel metrics={streamMetrics} />
                </div>
              </Panel>
            </div>

            <div className="grid gap-4 xl:grid-cols-3">
              <Panel>
                <PanelHeader
                  title="Attack surface"
                  description="Typed non-agent nodes and how many have fallen."
                  actions={
                    <Link
                      href="/topology"
                      className="text-2xs font-medium text-accent hover:text-accent-hover"
                    >
                      Open topology →
                    </Link>
                  }
                />
                <AttackSurfacePanel graph={insights.graph} />
              </Panel>

              <Panel>
                <PanelHeader
                  title="Choke points"
                  description="Highest betweenness centrality — containing these disconnects the most."
                />
                <CriticalNodesPanel nodes={insights.criticalNodes} graph={insights.graph} />
              </Panel>

              <Panel flush>
                <PanelHeader
                  bordered
                  title="Recent activity"
                  actions={
                    <Link
                      href="/activity"
                      className="text-2xs font-medium text-accent hover:text-accent-hover"
                    >
                      Full log →
                    </Link>
                  }
                />
                <div className="h-64">
                  <EventFeed
                    events={stream.recentEvents.slice(-40)}
                    emptyTitle={
                      liveLogGapHint(control.status, stream.recentEvents.length > 0)
                        ? "No events in this session"
                        : "No events yet"
                    }
                    emptyHint={liveLogGapHint(control.status, stream.recentEvents.length > 0)}
                  />
                </div>
              </Panel>
            </div>

            <Panel>
              <PanelHeader
                title="Remediation findings"
                description="Deterministic, rule-based recommendations derived from this run's graph and metrics."
                actions={
                  <ButtonLink href="/remediation" size="sm">
                    Validate fixes
                  </ButtonLink>
                }
              />
              {insights.remediation ? (
                <FindingsList
                  recommendations={insights.remediation.recommendations}
                  baseConfig={config ?? null}
                />
              ) : (
                <StatListSkeleton rows={2} />
              )}
            </Panel>

            <Disclaimer>
              Simulation results only — reproducible from{" "}
              <span className="font-mono">(seed, config)</span>, but not real-world security
              evidence about any deployed system.
            </Disclaimer>
          </>
        )}
      </div>
    </div>
  );
}

function LaunchHero() {
  return (
    <header className="border-b border-line px-5 py-6 lg:px-6 lg:py-7">
      <div className="max-w-3xl">
        <span className="mb-3 inline-flex items-center gap-2 rounded-full border border-line bg-raised px-2.5 py-1 text-2xs text-fg-muted">
          <BrandMark className="size-3.5 text-accent" />
          Multi-agent adversarial resilience platform
        </span>
        <h1 className="text-2xl font-semibold tracking-tight text-fg">
          Find out how far one compromised agent gets.
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-fg-muted">
          Model an agent system as a typed security graph — agents, tools, credentials, resources
          and the sentinels watching them — then run adversarial scenarios against it. Watch
          compromise propagate tick by tick, trace any incident back to patient zero, measure
          security against the utility it costs, and validate that a proposed fix actually changes
          the outcome.
        </p>
        <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-2xs text-fg-subtle">
          <li>Deterministic — same seed, same run, every time</li>
          <li>Event-sourced — every claim traces to a recorded event</li>
          <li>Six attack scenarios, from lateral spread to sentinel subversion</li>
        </ul>
      </div>
    </header>
  );
}

function buildStages({
  hasRun,
  observedEvents,
  compromised,
  hasMetrics,
  findings,
}: {
  hasRun: boolean;
  observedEvents: number;
  compromised: number;
  hasMetrics: boolean;
  findings: number;
}): Stage[] {
  const stage = (done: boolean, active: boolean) =>
    done ? ("done" as const) : active ? ("active" as const) : ("pending" as const);

  return [
    {
      id: "map",
      label: "Map",
      description: "Model the agent system as a typed security graph.",
      href: "/topology",
      state: stage(hasRun, !hasRun),
    },
    {
      id: "attack",
      label: "Attack",
      description: "Run adversarial scenarios against it.",
      href: "/",
      state: stage(hasRun && observedEvents > 0, hasRun && observedEvents === 0),
    },
    {
      id: "observe",
      label: "Observe",
      description: "Watch compromise and containment propagate.",
      href: "/activity",
      state: stage(compromised > 0 || observedEvents > 20, observedEvents > 0),
    },
    {
      id: "measure",
      label: "Measure",
      description: "Score security against retained utility.",
      href: "/metrics",
      state: stage(hasMetrics, hasRun),
    },
    {
      id: "remediate",
      label: "Remediate",
      description: "Get a config change that would have changed the outcome.",
      href: "/remediation",
      state: stage(findings > 0, hasMetrics),
    },
    {
      id: "retest",
      label: "Re-test",
      description: "Re-run with the fix applied and compare the numbers.",
      href: "/remediation",
      state: stage(false, findings > 0),
    },
  ];
}
