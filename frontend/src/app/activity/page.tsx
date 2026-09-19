"use client";

import { useMemo } from "react";

import { EventFeed } from "@/components/activity/EventFeed";
import { EventRow } from "@/components/activity/EventRow";
import { PageHeader } from "@/components/shell/AppShell";
import { RequiresRun } from "@/components/shell/RequiresRun";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { StatList, StatRow } from "@/components/ui/Metric";
import { EmptyState } from "@/components/ui/States";
import { useExperiment } from "@/lib/experiment/ExperimentProvider";
import { liveLogGapHint } from "@/lib/stream/sessionScope";
import { EVENT_LOG_CAP, type Event } from "@/lib/stream/reducer";
import { eventMeta, eventSeverity, EVENT_CATEGORY_LABEL, type EventCategory } from "@/lib/vocabulary";

export default function ActivityPage() {
  return (
    <RequiresRun
      title="No activity to observe"
      description="The activity log streams every event the simulation emits — compromise attempts, detections, quarantines, model calls and security-plane violations."
    >
      {(experimentId) => <ActivityContent experimentId={experimentId} />}
    </RequiresRun>
  );
}

function ActivityContent({ experimentId }: { experimentId: string }) {
  const { control, stream } = useExperiment();
  const events = stream.recentEvents;
  const gapHint = liveLogGapHint(control.status, events.length > 0);

  const byCategory = useMemo(() => {
    const counts = new Map<EventCategory, number>();
    for (const event of events) {
      const category = eventMeta(event.event_type).category;
      counts.set(category, (counts.get(category) ?? 0) + 1);
    }
    return counts;
  }, [events]);

  const criticalEvents = useMemo(
    () =>
      events.filter(
        (event) => eventSeverity(event.event_type, event.metadata ?? null) === "critical",
      ),
    [events],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        eyebrow="Observe"
        title="Live activity"
        description={
          <>
            Every event the engine emitted, newest first. The client keeps the most recent{" "}
            {EVENT_LOG_CAP} events of the run in memory — the full log is persisted and available
            under Runs.
          </>
        }
        className="py-3"
      />

      <div className="grid min-h-0 flex-1 gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_320px] lg:p-5">
        <Panel flush className="min-h-96 lg:min-h-0">
          <PanelHeader bordered title="Event log" />
          <EventFeed
            events={events}
            className="min-h-0 flex-1"
            emptyTitle={gapHint ? "No events in this session" : "No events yet"}
            emptyHint={gapHint ?? "Events appear as soon as the first tick is published."}
            emptyAction={
              gapHint ? (
                <ButtonLink size="sm" href={`/history/${experimentId}`}>
                  Replay the full log
                </ButtonLink>
              ) : undefined
            }
          />
        </Panel>

        <div className="flex min-h-0 flex-col gap-4">
          <Panel>
            <PanelHeader title="Event mix" description="What this run is mostly made of." />
            <StatList>
              {(Object.keys(EVENT_CATEGORY_LABEL) as EventCategory[]).map((category) => (
                <StatRow
                  key={category}
                  label={EVENT_CATEGORY_LABEL[category]}
                  value={byCategory.get(category) ?? 0}
                />
              ))}
            </StatList>
          </Panel>

          <Panel flush className="min-h-0 flex-1">
            <PanelHeader
              bordered
              title="Critical events"
              actions={
                <Badge severity={criticalEvents.length > 0 ? "critical" : "ok"}>
                  {criticalEvents.length}
                </Badge>
              }
            />
            {criticalEvents.length === 0 ? (
              <EmptyState
                compact
                title="No critical events"
                description="Successful compromises, policy violations and accepted attestation replays would appear here."
              />
            ) : (
              <ul className="min-h-0 flex-1 divide-y divide-line/50 overflow-y-auto px-3 py-1">
                {[...criticalEvents].reverse().map((event: Event) => (
                  <EventRow key={event.event_id} event={event} compact />
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
