"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AttackBanner } from "@/components/demo/AttackBanner";
import { ContainmentPanel } from "@/components/demo/ContainmentPanel";
import { IncidentStage } from "@/components/demo/IncidentStage";
import { NarrativeTimeline } from "@/components/demo/NarrativeTimeline";
import { RunHeader } from "@/components/demo/RunHeader";
import { Section } from "@/components/demo/Section";
import { TestEvidencePanel } from "@/components/demo/TestEvidencePanel";
import { VerdictStrip } from "@/components/demo/VerdictStrip";
import { Badge, SeverityDot } from "@/components/ui/Badge";
import { IconSpark } from "@/components/ui/icons";
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
  useEffect(() => {
    if (!sessionId || !verdict.attackDetected) return;
    if (explainedFor.current === sessionId) return;
    explainedFor.current = sessionId;

    const controller = new AbortController();
    void getRuntimeExplanation(sessionId, controller.signal)
      .then(setExplanation)
      .catch(() => setExplanation(null));
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
        <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-7 px-6 py-6">
          {loadError && (
            <ErrorState
              title="Cannot reach the AgentShield control plane"
              detail={`${loadError} — check that the backend is running and that NEXT_PUBLIC_BACKEND_URL points at its port.`}
            />
          )}
          {schemaError && (
            <ErrorState title="Event stream schema mismatch" detail={schemaError} />
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
              </Section>

              <Section
                step="03"
                title="The incident"
                description="What AgentShield blocked, and what it did next."
              >
                <AttackBanner incident={incident} />

                <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
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
                  <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                    <VerificationPanel verdict={verdict} />
                    <ArtifactPanel summary={summary} />
                  </div>
                </div>
              </Section>

              <Section
                step="05"
                title="The explanation"
                description="AI-generated commentary on a decision that was already made."
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
            <Panel>
              <EmptyState
                icon={<IconSpark className="size-5" />}
                title="No live swarm session"
                description={
                  <>
                    Start the AgentShield backend, then launch the WorkSwarm run. This screen
                    attaches to the session it creates and narrates it as it happens.
                  </>
                }
                action={
                  <code className="rounded-md border border-line bg-raised px-2.5 py-1.5 font-mono text-xs text-fg">
                    {LAUNCH_COMMAND}
                  </code>
                }
              />
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

// --- the task -------------------------------------------------------------

function ObjectiveBar({ summary }: { summary: RuntimeSessionSummary }) {
  return (
    <Panel className="gap-1.5">
      <p className="text-sm leading-6 text-fg">&ldquo;{summary.objective}&rdquo;</p>
    </Panel>
  );
}

// --- the explanation -----------------------------------------------------

function ExplanationPanel({ explanation }: { explanation: IncidentExplanation | null }) {
  if (!explanation?.available) {
    return (
      <Panel>
        <EmptyState
          compact
          title="No explanation yet"
          description="Written once an incident exists, and never before it."
        />
      </Panel>
    );
  }

  return (
    <Panel>
      <PanelHeader
        title={explanation.label}
        description={
          explanation.source === "openai"
            ? `Generated by ${explanation.model}`
            : "Generated locally, without a model"
        }
        actions={<Badge severity="neutral">{explanation.source}</Badge>}
      />
      <p className="text-xs leading-5 text-fg-muted">{explanation.body}</p>
      <p className="mt-3 text-2xs leading-4 text-fg-subtle">{explanation.authority}</p>
    </Panel>
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
