"use client";

import { useEffect, useState, type ReactNode } from "react";

import { SeverityDot } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { BrandMark } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import type { RuntimeSessionSummary, WorkflowState } from "@/lib/runtime/client";
import { elapsedMs, formatDuration, type RunWindow } from "@/lib/runtime/clock";
import type { ProvenanceIndex } from "@/lib/runtime/provenance";
import { SEVERITY_TEXT, type Severity } from "@/lib/severity";

/**
 * The one line a judge reads first: what state is this run in.
 *
 * Everything else up here is metadata and is sized like metadata. The state
 * word is the only thing in the header allowed to carry a severity colour,
 * so "RECOVERED" is legible from the back of a room and nothing competes
 * with it.
 */

type StateCopy = { label: string; severity: Severity; hint: string };

const RUN_STATE: Record<WorkflowState, StateCopy> = {
  idle: { label: "Idle", severity: "neutral", hint: "Waiting for the swarm to start." },
  running: { label: "Running", severity: "neutral", hint: "The team is working." },
  under_attack: {
    label: "Contained",
    severity: "critical",
    hint: "A worker broke policy and was quarantined.",
  },
  recovering: {
    label: "Recovering",
    severity: "contained",
    hint: "A replacement worker has the task.",
  },
  recovered: {
    label: "Recovered",
    severity: "ok",
    hint: "The workflow finished despite the compromise.",
  },
  failed: { label: "Failed", severity: "high", hint: "The workflow did not complete." },
};

const LIVE_STATES: ReadonlySet<WorkflowState> = new Set(["running", "under_attack", "recovering"]);

export function RunHeader({
  summary,
  provenance,
  window,
  connected,
  onReset,
  resetting,
}: {
  summary: RuntimeSessionSummary | null;
  provenance: ProvenanceIndex;
  window: RunWindow;
  connected: boolean;
  onReset: () => void;
  resetting: boolean;
}) {
  const state = RUN_STATE[summary?.workflow_state ?? "idle"];
  const live = summary ? LIVE_STATES.has(summary.workflow_state) : false;
  const elapsed = useElapsed(window, live);

  return (
    <header className="sticky top-0 z-20 border-b border-line bg-canvas/90 backdrop-blur">
      <div className="mx-auto flex w-full max-w-[1500px] flex-wrap items-center gap-x-5 gap-y-3 px-6 py-3.5">
        <div className="flex min-w-0 items-center gap-3">
          <BrandMark className="shrink-0 text-accent" />
          <div className="min-w-0">
            <h1 className="truncate text-base font-semibold tracking-tight text-fg">
              Live Swarm Defense
            </h1>
            {/* The strapline is the first thing to go when the header is
                tight: the state word and the metadata both outrank it. */}
            <p className="hidden truncate text-2xs text-fg-subtle 2xl:block">
              A real WorkSwarm team under a deterministic control plane
            </p>
          </div>
        </div>

        <div className="flex min-w-0 items-center gap-2.5">
          <SeverityDot severity={state.severity} pulse={live} className="size-2" />
          <div className="min-w-0">
            <p
              className={cn(
                "text-lg font-semibold uppercase leading-6 tracking-[0.12em]",
                SEVERITY_TEXT[state.severity],
              )}
            >
              {state.label}
            </p>
            <p className="hidden truncate text-2xs text-fg-subtle xl:block">{state.hint}</p>
          </div>
        </div>

        <dl className="ml-auto flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1.5 2xl:gap-x-5">
          <Meta label="Swarm">WorkSwarm</Meta>
          <Meta label="Model">
            {provenance.primary ? (
              <span title={`${provenance.calls} real model call(s)`}>
                {provenance.primary.model}
                <span className="text-fg-subtle">
                  {" · "}
                  {provenance.primary.provider}
                </span>
              </span>
            ) : (
              // With no session there is nothing to report yet; with one, the
              // absence of a model call is itself worth saying.
              <span className="text-fg-subtle">
                {summary ? "no model call recorded" : "—"}
              </span>
            )}
          </Meta>
          <Meta label="Session">
            {summary ? (
              <span title={summary.session_id}>{summary.session_id.slice(0, 8)}</span>
            ) : (
              <span className="text-fg-subtle">—</span>
            )}
          </Meta>
          <Meta label="Elapsed">{formatDuration(elapsed)}</Meta>
          <Meta label="Stream">
            <span className="inline-flex items-center gap-1.5">
              <SeverityDot severity={connected ? "ok" : "neutral"} />
              <span className={connected ? undefined : "text-fg-subtle"}>
                {connected ? "live" : "idle"}
              </span>
            </span>
          </Meta>
        </dl>

        <Button variant="default" size="sm" onClick={onReset} disabled={resetting}>
          {resetting ? "Resetting…" : "Reset demo"}
        </Button>
      </div>

    </header>
  );
}

function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="eyebrow leading-none">{label}</dt>
      <dd className="min-w-0 truncate font-mono text-2xs tabular text-fg-muted">{children}</dd>
    </div>
  );
}

/** Ticks only while the run is live; a finished run's duration is a constant. */
function useElapsed(window: RunWindow, live: boolean): number | null {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [live]);

  return elapsedMs(window, { live, now });
}
