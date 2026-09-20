"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { EventFeed } from "@/components/activity/EventFeed";
import { SeverityDot } from "@/components/ui/Badge";
import { SegmentedControl } from "@/components/ui/Button";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { EmptyState } from "@/components/ui/States";
import { cn } from "@/lib/cn";
import { deriveNarrative, type Beat } from "@/lib/runtime/narrative";
import { SEVERITY_TEXT } from "@/lib/severity";
import type { Event } from "@/lib/stream/reducer";

/**
 * The run's story, with the raw stream one click behind it.
 *
 * Default view is the narrative: the beats a judge is meant to read, with
 * everything else folded into the worker that produced it. "Full stream" is
 * the untouched log, because the claim that nothing is hidden has to be
 * checkable — the narrative is a lens on the events, not a replacement for
 * them.
 *
 * Oldest first, unlike the operator log. This is a story, and a story read
 * bottom-up is not one.
 */

const VIEWS = [
  { value: "story" as const, label: "Story" },
  { value: "stream" as const, label: "Full stream" },
];

export function NarrativeTimeline({ events }: { events: Event[] }) {
  const [view, setView] = useState<"story" | "stream">("story");
  const beats = useMemo(() => deriveNarrative(events), [events]);

  return (
    <Panel flush className="min-h-0">
      <PanelHeader
        bordered
        title="Incident timeline"
        description={
          view === "story"
            ? `${beats.length} beats from ${events.length} recorded events`
            : "Every event on the live stream, untouched"
        }
        actions={
          <SegmentedControl
            ariaLabel="Timeline detail"
            value={view}
            onChange={setView}
            options={VIEWS}
          />
        }
      />
      {view === "story" ? <Story beats={beats} /> : <EventFeed events={events} />}
    </Panel>
  );
}

function Story({ beats }: { beats: Beat[] }) {
  const listRef = useRef<HTMLOListElement>(null);
  const latest = beats.at(-1)?.id;

  // Follow the story as it is told, but only when the reader is already at the
  // end of it — and by scrolling this list rather than calling scrollIntoView,
  // which walks up the ancestors and would yank the whole page down mid-read.
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const distanceFromBottom = list.scrollHeight - list.scrollTop - list.clientHeight;
    if (distanceFromBottom > 120) return;
    list.scrollTop = list.scrollHeight;
  }, [latest]);

  if (beats.length === 0) {
    return (
      <EmptyState
        compact
        className="flex-1"
        title="No events yet"
        description="The story fills in as the WorkSwarm workflow runs."
      />
    );
  }

  return (
    <ol ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
      {beats.map((beat, index) => (
        <li key={beat.id} className="flex min-w-0 gap-3">
          <Rail beat={beat} first={index === 0} last={index === beats.length - 1} />
          <div
            className={cn(
              "min-w-0 flex-1 pb-3",
              beat.kind === "activity" && "opacity-70",
            )}
          >
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
              <span
                className={cn(
                  "text-xs font-semibold",
                  beat.kind === "milestone" ? SEVERITY_TEXT[beat.severity] : "text-fg-muted",
                )}
              >
                {beat.label}
              </span>
              {beat.kind === "milestone" && beat.actorRole && (
                <span className="truncate text-2xs text-fg-subtle">{beat.actorRole}</span>
              )}
              {beat.count > 1 && (
                <span className="font-mono text-2xs text-fg-subtle">
                  {beat.count} events
                </span>
              )}
            </div>
            {beat.detail && (
              <p
                className="mt-0.5 line-clamp-2 text-2xs leading-4 text-fg-subtle"
                title={beat.detail}
              >
                {beat.detail}
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** The vertical spine. A milestone gets a filled dot; activity gets a tick. */
function Rail({ beat, first, last }: { beat: Beat; first: boolean; last: boolean }) {
  return (
    <div aria-hidden className="flex w-3 shrink-0 flex-col items-center">
      <span className={cn("w-px flex-none", first ? "h-1.5 bg-transparent" : "h-1.5 bg-line")} />
      {beat.kind === "milestone" ? (
        <SeverityDot severity={beat.severity} />
      ) : (
        <span className="size-1 rounded-full bg-line-strong" />
      )}
      <span className={cn("w-px flex-1", last ? "bg-transparent" : "bg-line")} />
    </div>
  );
}
