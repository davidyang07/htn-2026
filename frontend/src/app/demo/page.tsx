"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AttackBanner } from "@/components/demo/AttackBanner";
import { ContainmentPanel } from "@/components/demo/ContainmentPanel";
import { ExplanationPanel } from "@/components/demo/ExplanationPanel";
import { IdleState } from "@/components/demo/IdleState";
import { IncidentStage } from "@/components/demo/IncidentStage";
import { NarrativeTimeline } from "@/components/demo/NarrativeTimeline";
import { ProvenanceBar } from "@/components/demo/ProvenanceBar";
import { RunHeader } from "@/components/demo/RunHeader";
import { Section } from "@/components/demo/Section";
import { TestEvidencePanel } from "@/components/demo/TestEvidencePanel";
import { VerdictStrip } from "@/components/demo/VerdictStrip";
import { Badge, SeverityDot } from "@/components/ui/Badge";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { EmptyState, ErrorState } from "@/components/ui/States";
import {
  NoLiveSessionError,
  getCurrentRuntimeSession,
  getRuntimeExplanation,
  resetRuntimeSessions,
  type IncidentExplanation,
  type RuntimeSessionSummary,
} from "@/lib/runtime/client";
import { runWindow } from "@/lib/runtime/clock";
import { deriveIncident } from "@/lib/runtime/incident";
import { deriveProvenance } from "@/lib/runtime/provenance";
import { buildStage } from "@/lib/runtime/stage";
import { deriveTestEvidence } from "@/lib/runtime/testRuns";
import { useRuntimeStream } from "@/lib/runtime/useRuntimeStream";
import { deriveVerdict, verdictLights } from "@/lib/runtime/verdict";

const POLL_MS = 1500;
const LAUNCH_COMMAND = "python workswarm/run_demo.py";

export default function DemoPage() {
  const [summary, setSummary] = useState<RuntimeSessionSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [explanation, setExplanation] = useState<IncidentExplanation | null>(null);
  const [resetting, setResetting] = useState(false);
  const explainedFor = useRef<string | null>(null);

  const sessionId = summary?.session_id ?? null;
  const { state, schemaError, connected } = useRuntimeStream(sessionId);

  // Poll for "the session the WorkSwarm run just created". The screen is
  // opened before the swarm is launched, so there is genuinely nothing to
  // attach to until there is.
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function poll() {
      try {
        const next = await getCurrentRuntimeSession(controller.signal);
        if (!cancelled) {
          setSummary(next);
          setLoadError(null);
        }
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        if (err instanceof NoLiveSessionError) {
          setSummary(null);
          setLoadError(null);
        } else {
          setLoadError(err instanceof Error ? err.message : String(err));
        }
      }
    }

    void poll();
    const timer = setInterval(() => void poll(), POLL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      clearInterval(timer);
    };
  }, []);

  // Scope everything read off the stream to the session currently attached.
  // After a reset the socket's last frames are still in `state`, and a verdict
  // light left over from a previous run is a light that lies.
  const liveEvents = useMemo(
    () => (sessionId && state.experimentId === sessionId ? state.recentEvents : []),
    [sessionId, state.experimentId, state.recentEvents],
  );
  const verdict = useMemo(() => deriveVerdict(liveEvents), [liveEvents]);
  const lights = useMemo(() => verdictLights(verdict), [verdict]);
  const provenance = useMemo(() => deriveProvenance(liveEvents), [liveEvents]);
  const incident = useMemo(() => deriveIncident(liveEvents), [liveEvents]);
  const testEvidence = useMemo(() => deriveTestEvidence(liveEvents), [liveEvents]);
  const clock = useMemo(() => runWindow(liveEvents), [liveEvents]);

  // The explanation is post-hoc commentary on an already-recorded decision, so
  // it is fetched once the incident exists and never before it.
  //
  // The guard is set on *success*, not before the request. Set beforehand it
  // cannot survive an aborted request — React's development double-invoke
  // aborts the first one, and the second render then reads the guard as
  // "already fetched" and never asks again, leaving a run that has an
  // explanation showing "no explanation yet" for the whole demo.
  useEffect(() => {
    if (!sessionId || !verdict.attackDetected) return;
    if (explainedFor.current === sessionId) return;

    const controller = new AbortController();
    void getRuntimeExplanation(sessionId, controller.signal)
      .then((next) => {
        explainedFor.current = sessionId;
        setExplanation(next);
      })
      // Aborted or failed: leave the guard clear so the next attach retries.
      .catch(() => {});
    return () => controller.abort();
  }, [sessionId, verdict.attackDetected]);

  const onReset = useCallback(async () => {
    setResetting(true);
    try {
      await resetRuntimeSessions();
      setSummary(null);
      setExplanation(null);
      explainedFor.current = null;
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setResetting(false);
    }
  }, []);

  const stage = useMemo(() => buildStage(summary, state), [summary, state]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <RunHeader
        summary={summary}
        provenance={provenance}
        window={clock}
        connected={connected}
        onReset={onReset}
        resetting={resetting}
      />

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-9 px-6 py-7 pb-16">
          {/* A load failure while a session is on screen keeps the screen: the
              events already streamed are still true, and blanking them would
              throw away the part of the run that did happen. With no session
              the idle state carries the failure instead. */}
          {loadError && summary && (
            <ErrorState
              title="Lost contact with the AgentShield control plane"
              detail={`${loadError} — the run below is the last state received.`}
            />
          )}
          {schemaError && (
            <ErrorState
              title="Event stream schema mismatch"
              detail={`${schemaError} — the stream stopped here rather than showing events it could not read.`}
            />
          )}

          {summary ? (
            <>
              <Section
                step="01"
                title="The task"
                description="What the user asked the team to do."
              >
                <ObjectiveBar summary={summary} />
              </Section>

              <Section
                step="02"
                title="The swarm"
                description="Who handed work to whom, and where the chain broke."
              >
                <IncidentStage stage={stage} provenance={provenance} />
                <ProvenanceBar provenance={provenance} />
              </Section>

              <Section
                step="03"
                title="The incident"
                description="What AgentShield blocked, and what it did next."
              >
                <AttackBanner incident={incident} />

                <div className="grid min-h-0 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                  <ContainmentPanel incident={incident} artifacts={summary.artifacts} />
                  <div className="flex min-h-0 max-h-[34rem] flex-col">
                    <NarrativeTimeline events={liveEvents} />
                  </div>
                </div>
              </Section>

              <Section
                step="04"
                title="The evidence"
                description="What proves the job still got done."
              >
                <div className="flex flex-col gap-4">
                  <TestEvidencePanel evidence={testEvidence} />
                  <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                    <VerificationPanel verdict={verdict} />
                    <ArtifactPanel summary={summary} />
                  </div>
                </div>
              </Section>

              <Section
                step="05"
                title="The explanation"
                description="Post-hoc commentary on a decision that was already made."
              >
                <ExplanationPanel explanation={explanation} />
              </Section>

              <Section
                step="06"
                title="The verdict"
                description="Every light below is set by a recorded event, never by a claim."
              >
                <VerdictStrip lights={lights} />
              </Section>
            </>
          ) : (
            <IdleState
              status={loadError ? "unreachable" : "waiting"}
              detail={loadError}
              command={LAUNCH_COMMAND}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// --- the task -------------------------------------------------------------

function ObjectiveBar({ summary }: { summary: RuntimeSessionSummary }) {
  // A quotation, not a readout: one rule and open space carry it, where a
  // full bordered panel around a single sentence made it look like a metric.
  return (
    <blockquote className="border-l-2 border-accent-line pl-4">
      <p className="max-w-4xl text-base leading-7 text-fg">
        &ldquo;{summary.objective}&rdquo;
      </p>
    </blockquote>
  );
}

// --- verification ---------------------------------------------------------

const STEP_LABEL: Record<string, string> = {
  analysis: "Repository analysed",
  research: "Vulnerability investigated",
  patch: "Patch applied",
  pytest: "Tests run",
  review: "Independently reviewed",
};

function VerificationPanel({ verdict }: { verdict: ReturnType<typeof deriveVerdict> }) {
  return (
    <Panel>
      <PanelHeader
        title="Work completed"
        description="Each step a worker actually finished, in the order it happened."
      />

      {verdict.completedSteps.length === 0 ? (
        <EmptyState compact title="Nothing completed yet" />
      ) : (
        <ol className="flex flex-col gap-1.5">
          {verdict.completedSteps.map((step) => (
            <li key={step.seq} className="flex items-baseline gap-2 text-xs">
              <SeverityDot severity="ok" className="translate-y-[-1px]" />
              <span className="shrink-0 font-medium text-fg">
                {STEP_LABEL[step.step] ?? step.step}
              </span>
              <span className="min-w-0 flex-1 truncate text-fg-subtle" title={step.detail}>
                {step.detail}
              </span>
              {step.workerId && (
                <span className="shrink-0 font-mono text-2xs text-fg-subtle">
                  {step.workerId}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

// --- artifacts ------------------------------------------------------------

function ArtifactPanel({ summary }: { summary: RuntimeSessionSummary }) {
  if (summary.artifacts.length === 0) return null;

  return (
    <Panel flush>
      <PanelHeader
        bordered
        title="Artifacts and trust"
        description="An untrusted artifact is excluded from every downstream worker's context."
      />
      <ul className="divide-y divide-line/60">
        {summary.artifacts.map((artifact) => (
          <li
            key={artifact.id}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-xs"
          >
            <span className="shrink-0 font-mono text-2xs text-fg">{artifact.id}</span>
            <Badge severity={artifact.trusted ? "ok" : "critical"}>
              {artifact.trusted ? "trusted" : "untrusted"}
            </Badge>
            <span className="shrink-0 text-2xs text-fg-subtle">
              {artifact.kind} · {artifact.worker_id}
            </span>
            <span className="ml-auto min-w-0 flex-1 truncate text-right text-2xs text-fg-subtle">
              {artifact.taint_reason ?? artifact.summary}
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
