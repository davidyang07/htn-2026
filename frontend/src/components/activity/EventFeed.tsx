"use client";

import { useMemo, useState, type ReactNode } from "react";

import { EventRow } from "@/components/activity/EventRow";
import { SegmentedControl } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { EmptyState } from "@/components/ui/States";
import { cn } from "@/lib/cn";
import type { Event } from "@/lib/stream/reducer";
import { eventMeta, EVENT_CATEGORY_LABEL, type EventCategory } from "@/lib/vocabulary";

type Filter = "all" | EventCategory;

const FILTERS: ReadonlyArray<{ value: Filter; label: string }> = [
  { value: "all", label: "All" },
  { value: "attack", label: EVENT_CATEGORY_LABEL.attack },
  { value: "defense", label: EVENT_CATEGORY_LABEL.defense },
  { value: "security-plane", label: "Plane" },
  { value: "model", label: EVENT_CATEGORY_LABEL.model },
];

/**
 * The live event log, filterable by what an operator actually asks of it:
 * "show me only the attacks", "only what the defense did", "everything about
 * agent-017". The previous flat mono dump answered none of those.
 */
export function EventFeed({
  events,
  onSelectAgent,
  className,
  emptyTitle,
  emptyHint,
  emptyAction,
}: {
  events: Event[];
  onSelectAgent?: (agentId: string) => void;
  className?: string;
  emptyTitle?: string;
  emptyHint?: string;
  emptyAction?: ReactNode;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return events.filter((event) => {
      if (filter !== "all" && eventMeta(event.event_type).category !== filter) return false;
      if (!needle) return true;
      return (
        event.event_type.toLowerCase().includes(needle) ||
        (event.agent_id ?? "").toLowerCase().includes(needle) ||
        (event.source_agent_id ?? "").toLowerCase().includes(needle) ||
        (event.target_agent_id ?? "").toLowerCase().includes(needle)
      );
    });
  }, [events, filter, query]);

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <SegmentedControl
          ariaLabel="Filter events by category"
          value={filter}
          onChange={setFilter}
          options={FILTERS}
        />
        <TextField
          aria-label="Filter events by agent or type"
          placeholder="Filter by agent or event type…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="h-7 min-w-40 max-w-64 flex-1 text-xs"
        />
        <span className="ml-auto shrink-0 font-mono text-2xs tabular text-fg-subtle">
          {filtered.length}
          {filtered.length !== events.length && ` / ${events.length}`} events
        </span>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          compact
          className="flex-1"
          title={
            events.length === 0
              ? (emptyTitle ?? "No events yet")
              : "No events match this filter"
          }
          description={
            events.length === 0
              ? (emptyHint ?? "Events stream in as the simulation ticks.")
              : "Try a different category, or clear the text filter."
          }
          action={events.length === 0 ? emptyAction : undefined}
        />
      ) : (
        <ul className="min-h-0 flex-1 divide-y divide-line/50 overflow-y-auto px-3 py-1">
          {[...filtered].reverse().map((event) => (
            <EventRow key={event.event_id} event={event} onSelectAgent={onSelectAgent} />
          ))}
        </ul>
      )}
    </div>
  );
}
