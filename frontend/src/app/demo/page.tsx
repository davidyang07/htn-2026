"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EventFeed } from "@/components/activity/EventFeed";
import { IncidentStage } from "@/components/demo/IncidentStage";
import { RunHeader } from "@/components/demo/RunHeader";
import { Section } from "@/components/demo/Section";
import { Badge, SeverityDot } from "@/components/ui/Badge";
import { IconAlert, IconShieldCheck, IconSpark } from "@/components/ui/icons";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { cn } from "@/lib/cn";
import {
  NoLiveSessionError,
  getCurrentRuntimeSession,
  getRuntimeExplanation,
  resetRuntimeSessions,
  type IncidentExplanation,
  type RuntimeSessionSummary,
} from "@/lib/runtime/client";
import { runWindow } from "@/lib/runtime/clock";
import { deriveProvenance } from "@/lib/runtime/provenance";
import { buildStage } from "@/lib/runtime/stage";
import { useRuntimeStream } from "@/lib/runtime/useRuntimeStream";
import { deriveVerdict, verdictLights, type VerdictLight } from "@/lib/runtime/verdict";
import { SEVERITY_TEXT, type Severity } from "@/lib/severity";

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
                description="Recorded deterministically, before anything was read."
              >
                <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                  <IncidentPanel
                    verdict={verdict}
                    summary={summary}
                    explanation={explanation}
                  />
                  <Panel flush className="min-h-0 max-h-[32rem]">
                    <PanelHeader
                      bordered
                      title="Incident timeline"
                      description="Every line is a real event on the live stream."
                    />
                    <EventFeed
                      className="min-h-0 flex-1"
                      events={liveEvents}
                      emptyTitle="No events yet"
                      emptyHint="The timeline fills as the WorkSwarm workflow runs."
                    />
                  </Panel>
                </div>
              </Section>

              <Section
                step="04"
                title="The evidence"
                description="What proves the job still got done."
              >
                <div className="flex flex-col gap-4">
                  <VerificationPanel verdict={verdict} summary={summary} />
                  <ArtifactPanel summary={summary} />
                </div>
              </Section>

              <Section
                step="05"
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

// --- the verdict strip ----------------------------------------------------

const LIGHT_SEVERITY: Record<VerdictLight["status"], Severity> = {
  pending: "neutral",
  lit: "ok",
  failed: "critical",
};

function VerdictStrip({ lights }: { lights: VerdictLight[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {lights.map((light) => {
        const severity = LIGHT_SEVERITY[light.status];
        const on = light.status !== "pending";
        return (
          <div
            key={light.key}
            className={cn(
              "flex min-w-0 flex-col gap-1.5 rounded-lg border bg-surface p-3.5 transition-colors duration-300",
              on ? "border-line-strong" : "border-line",
            )}
          >
            <div className="flex items-center gap-2">
              <SeverityDot severity={severity} pulse={light.status === "lit"} />
              <span
                className={cn(
                  "truncate text-sm font-semibold uppercase tracking-wide",
                  on ? SEVERITY_TEXT[severity] : "text-fg-subtle",
                )}
              >
                {light.label}
              </span>
            </div>
            <p className="line-clamp-2 text-2xs leading-4 text-fg-subtle">{light.hint}</p>
          </div>
        );
      })}
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

// --- the incident ---------------------------------------------------------

function IncidentPanel({
  verdict,
  summary,
  explanation,
}: {
  verdict: ReturnType<typeof deriveVerdict>;
  summary: RuntimeSessionSummary;
  explanation: IncidentExplanation | null;
}) {
  if (!verdict.attackDetected) {
    return (
      <Panel>
        <PanelHeader
          title="Policy decision"
          description="Fills in the moment a worker asks for something outside its policy envelope."
        />
        <EmptyState
          compact
          icon={<IconShieldCheck className="size-5" />}
          title="No policy violation yet"
          description="Every resource request so far has been inside the sandbox."
        />
      </Panel>
    );
  }

  const tainted = summary.artifacts.filter((a) => !a.trusted);

  return (
    <Panel>
      <PanelHeader
        title="Policy decision"
        description="Denied synchronously — nothing was read."
        actions={
          <Badge severity="critical">
            <IconAlert className="size-3" />
            {verdict.violationType ?? "policy violation"}
          </Badge>
        }
      />

      <dl className="flex flex-col gap-2 text-xs">
        <Field label="Worker">
          <span className="font-mono">{verdict.quarantinedWorkerId ?? "—"}</span>
        </Field>
        <Field label="Requested">
          {/* The path only. Nothing opened it, so there is no content to show. */}
          <span className="break-all font-mono text-critical">
            {verdict.deniedResource ?? "—"}
          </span>
        </Field>
        <Field label="Policy">
          <span className="text-fg-muted">{verdict.violationReason ?? "—"}</span>
        </Field>
        <Field label="Output tainted">
          <span className="text-fg-muted">
            {tainted.length === 0
              ? "none recorded"
              : tainted.map((a) => a.id).join(", ")}
          </span>
        </Field>
        <Field label="Replaced by">
          <span className="font-mono">{verdict.replacementWorkerId ?? "—"}</span>
        </Field>
      </dl>

      {explanation?.available && (
        <div className="mt-3 rounded-md border border-line bg-raised p-3">
          <p className="eyebrow mb-1.5">
            Why this was suspicious ·{" "}
            {explanation.source === "openai"
              ? `post-hoc commentary from ${explanation.model}`
              : "post-hoc commentary, generated locally"}
          </p>
          <p className="text-xs leading-5 text-fg-muted">{explanation.body}</p>
          <p className="mt-2 text-2xs leading-4 text-fg-subtle">
            Commentary only. The deny and quarantine decision above was made deterministically
            and recorded before this was written; no model input reaches it.
          </p>
        </div>
      )}
    </Panel>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <dt className="w-28 shrink-0 text-2xs uppercase tracking-wide text-fg-subtle">{label}</dt>
      <dd className="min-w-0 flex-1">{children}</dd>
    </div>
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

function VerificationPanel({
  verdict,
  summary,
}: {
  verdict: ReturnType<typeof deriveVerdict>;
  summary: RuntimeSessionSummary;
}) {
  const testSeverity: Severity =
    verdict.testsPassed === true ? "ok" : verdict.testsPassed === false ? "critical" : "neutral";

  return (
    <Panel>
      <PanelHeader
        title="Verification"
        description="The team finished the job. This is the evidence, not a claim."
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

      <div className="mt-3 rounded-md border border-line bg-raised p-3">
        <p className="eyebrow mb-1.5">
          {verdict.testCommand ? `$ ${verdict.testCommand}` : "Real test run"}
        </p>
        <p className={cn("font-mono text-xs", SEVERITY_TEXT[testSeverity])}>
          {summary.test_summary ?? verdict.testSummary ?? "No test run reported yet."}
        </p>
        <p className="mt-2 text-2xs leading-4 text-fg-subtle">
          Verbatim from an actual <span className="font-mono">pytest</span> subprocess. A red run
          is reported red.
        </p>
      </div>
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
