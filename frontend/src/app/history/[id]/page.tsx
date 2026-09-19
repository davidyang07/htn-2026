"use client";

import Link from "next/link";
import { use, useEffect, useMemo, useReducer, useState } from "react";

import { EventFeed } from "@/components/activity/EventFeed";
import { TopologyWorkspace } from "@/components/graph/TopologyWorkspace";
import {
  formatMetric,
  METRIC_DESCRIPTORS,
  metricSeverity,
} from "@/components/insights/SecurityMetrics";
import { ReplayTransport } from "@/components/run/ReplayTransport";
import { PageHeader } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/Button";
import { IconArrowLeft, IconChevronDown, IconChevronRight } from "@/components/ui/icons";
import { ErrorState, Spinner, WarningBanner } from "@/components/ui/States";
import { cn } from "@/lib/cn";
import { shortId } from "@/lib/format";
import { initialReplayControlState, replayControlReducer } from "@/lib/replay/controlReducer";
import { useReplayStream } from "@/lib/replay/useReplayStream";
import { useSecurityInsights } from "@/lib/security/useSecurityInsights";
import { SEVERITY_TEXT } from "@/lib/severity";

// The four headline metrics, shown as a strip so the replay keeps its vertical
// space for the graph.
const STRIP_KEYS = [
  "compromise_fraction",
  "blast_radius_fraction",
  "retained_utility",
  "security_plane_integrity",
] as const;

export default function ReplayPage(props: PageProps<"/history/[id]">) {
  const { id } = use(props.params);
  return <ReplayContent key={id} experimentId={id} />;
}

// Keyed by experimentId in the parent so navigating to a different replay
// target remounts fresh -- useReplayStream relies on this.
function ReplayContent({ experimentId }: { experimentId: string }) {
  const [control, dispatch] = useReducer(replayControlReducer, initialReplayControlState);
  const { state, loading, loadedEvents, error, incomplete, totalEvents, playedCount, seek } = useReplayStream(
    experimentId,
    control.speed,
    control.playing,
  );
  const insights = useSecurityInsights(experimentId, "replay");
  // Collapsed by default: the graph is the point of this screen, and on a
  // laptop viewport an open log squeezes it to a strip.
  const [logOpen, setLogOpen] = useState(false);

  // Reacting to playback actually finishing (an external condition), not
  // setting state unconditionally at mount -- keeps the control's `playing`
  // flag, and hence the Play/Pause button's label, in sync once the last
  // event has played.
  useEffect(() => {
    if (control.playing && totalEvents > 0 && playedCount >= totalEvents) {
      dispatch({ type: "pause" });
    }
  }, [control.playing, playedCount, totalEvents]);

  const strip = useMemo(() => {
    if (!insights.metrics) return [];
    return STRIP_KEYS.map((key) => {
      const descriptor = METRIC_DESCRIPTORS.find((d) => d.key === key)!;
      const raw = insights.metrics![key];
      const value = typeof raw === "number" ? raw : null;
      return { descriptor, value };
    });
  }, [insights.metrics]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-xs text-fg-muted">
        <Spinner />
        Loading persisted event log…
        {loadedEvents > 0 && (
          <span className="font-mono tabular text-fg-subtle">{loadedEvents} events</span>
        )}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-5">
        <ErrorState title="Failed to load replay" detail={error} />
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col">
      <PageHeader
        eyebrow="Replay"
        title={`Run ${shortId(experimentId)}`}
        description="Reconstructed client-side from the persisted event log — one fetch, then play, pause, speed and scrub with no further network calls."
        className="py-3"
        actions={
          <Link
            href="/history"
            className="flex items-center gap-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
          >
            <IconArrowLeft className="size-3.5" />
            All runs
          </Link>
        }
      />

      {incomplete && (
        <WarningBanner className="mx-4 mt-3 lg:mx-5">
          This run is marked incomplete — persistence detected a gap, or the process never
          finalized it. Replay shows only what was actually recorded; treat its metrics as
          partial, not a trustworthy final result.
        </WarningBanner>
      )}

      <ReplayTransport
        control={control}
        dispatch={dispatch}
        totalEvents={totalEvents}
        playedCount={playedCount}
        onSeek={seek}
        tick={state.tick}
      />

      {strip.length > 0 && (
        <div className="flex shrink-0 flex-wrap items-center gap-x-6 gap-y-1 border-b border-line px-4 py-2">
          <span className="eyebrow">Final state</span>
          {strip.map(({ descriptor, value }) => (
            <span key={descriptor.key} className="flex items-baseline gap-1.5" title={descriptor.definition}>
              <span className="text-2xs text-fg-subtle">{descriptor.label}</span>
              <span
                className={cn(
                  "font-mono text-xs tabular",
                  value === null ? "text-fg-muted" : SEVERITY_TEXT[metricSeverity(descriptor, value)],
                )}
              >
                {formatMetric(descriptor, value)}
              </span>
            </span>
          ))}
          <span className="ml-auto text-2xs text-fg-subtle">
            Metrics reflect the run&apos;s reconstructed final state, not the scrubbed position.
          </span>
        </div>
      )}

      {/* A viewport-relative height rather than flex-1: the transport, the
          metric strip and the log all want space on this screen, and the graph
          losing the argument turns it into a strip. */}
      <div className="flex h-[clamp(340px,52vh,720px)] flex-col">
        <TopologyWorkspace
          experimentId={experimentId}
          stream={state}
          securityGraph={insights.graph}
          blastRadius={insights.blastRadius}
          mode="replay"
          loading={insights.loading}
        />
      </div>

      <div
        className={cn(
          "flex shrink-0 flex-col border-t border-line bg-surface",
          logOpen ? "h-52" : "h-9",
        )}
      >
        <Button
          variant="ghost"
          size="sm"
          className="h-9 justify-start rounded-none px-3"
          onClick={() => setLogOpen((v) => !v)}
          aria-expanded={logOpen}
        >
          {logOpen ? (
            <IconChevronDown className="size-3.5" />
          ) : (
            <IconChevronRight className="size-3.5" />
          )}
          Event log
          <span className="ml-2 font-mono text-2xs text-fg-subtle">
            {state.recentEvents.length} in view
          </span>
        </Button>
        {logOpen && (
          <EventFeed
            events={state.recentEvents}
            className="min-h-0 flex-1"
            emptyTitle="Nothing replayed yet"
            emptyHint="Press Play, or scrub the timeline, to step through this run's recorded events."
          />
        )}
      </div>
    </div>
  );
}
