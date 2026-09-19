"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { PageHeader } from "@/components/shell/AppShell";
import { Badge, ConfigChip } from "@/components/ui/Badge";
import { Button, ButtonLink, SegmentedControl } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { Mono, TableWrap, Td, Th, Tr } from "@/components/ui/Table";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { listExperiments, type ExperimentListItem } from "@/lib/api/client";
import { formatTimestamp, shortId } from "@/lib/format";
import { scenarioMeta } from "@/lib/vocabulary";

type StatusFilter = "all" | "finished" | "stopped" | "incomplete";
type DefenseFilter = "all" | "true" | "false";

const STATUS_OPTIONS = [
  { value: "all" as const, label: "All" },
  { value: "finished" as const, label: "Completed" },
  { value: "stopped" as const, label: "Stopped" },
  { value: "incomplete" as const, label: "Incomplete" },
];

const DEFENSE_OPTIONS = [
  { value: "all" as const, label: "Any defense" },
  { value: "true" as const, label: "Defended" },
  { value: "false" as const, label: "Undefended" },
];

function toListParams(status: StatusFilter, defenseEnabled: DefenseFilter) {
  return {
    status: status === "all" ? undefined : status,
    defenseEnabled: defenseEnabled === "all" ? undefined : defenseEnabled === "true",
  };
}

// Keyed by `${status}-${defenseEnabled}` in the parent so a filter change
// remounts this fresh -- mirrors the remount-by-key convention used for the
// live view, and keeps the mount effect's only setState calls inside the
// fetch's resolution callbacks (react-hooks/set-state-in-effect).
function HistoryList({
  status,
  defenseEnabled,
  selected,
  onToggleSelect,
}: {
  status: StatusFilter;
  defenseEnabled: DefenseFilter;
  selected: string[];
  onToggleSelect: (id: string) => void;
}) {
  const [items, setItems] = useState<ExperimentListItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listExperiments(toListParams(status, defenseEnabled)).then(
      (resp) => {
        if (cancelled) return;
        setItems(resp.items);
        setNextCursor(resp.next_cursor);
        setLoading(false);
      },
      (err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
    // status/defenseEnabled are fixed props for this component's lifetime --
    // the parent remounts it (via `key`) when a filter changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadMore() {
    if (!nextCursor) return;
    setLoading(true);
    try {
      const resp = await listExperiments({
        ...toListParams(status, defenseEnabled),
        cursor: nextCursor,
      });
      setItems((prev) => [...prev, ...resp.items]);
      setNextCursor(resp.next_cursor);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  if (error) {
    return <ErrorState className="m-4" title="Could not load run history" detail={error} />;
  }

  if (loading && items.length === 0) {
    return (
      <div className="flex flex-col gap-2 p-4">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-9 w-full" />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        title="No persisted runs match"
        description="Every assessment is persisted event by event as it runs. Launch one, or widen the filters above."
        action={
          <ButtonLink href="/" size="sm" variant="primary">
            Launch an assessment
          </ButtonLink>
        }
      />
    );
  }

  return (
    <>
      <TableWrap>
        <thead>
          <tr>
            <Th className="w-9" aria-label="Select for comparison" />
            <Th>Run</Th>
            <Th>Started</Th>
            <Th className="text-right">Seed</Th>
            <Th className="text-right">Agents</Th>
            <Th>Attack</Th>
            <Th>Defense</Th>
            <Th>Outcome</Th>
            <Th>Log integrity</Th>
            <Th className="w-20" />
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const isSelected = selected.includes(item.experiment_id);
            const scenarios = item.config.active_scenarios ?? [];
            return (
              <Tr key={item.experiment_id} selected={isSelected}>
                <Td>
                  <input
                    type="checkbox"
                    className="accent-accent"
                    checked={isSelected}
                    onChange={() => onToggleSelect(item.experiment_id)}
                    aria-label={`Select ${item.experiment_id} for comparison`}
                  />
                </Td>
                <Td>
                  <Mono>{shortId(item.experiment_id)}</Mono>
                </Td>
                <Td className="whitespace-nowrap">{formatTimestamp(item.created_at)}</Td>
                <Td className="text-right font-mono text-fg">{item.seed}</Td>
                <Td className="text-right font-mono text-fg">{item.config.node_count}</Td>
                <Td>
                  <span className="flex flex-wrap gap-1">
                    {scenarios.length === 0 ? (
                      <span className="text-fg-subtle">—</span>
                    ) : (
                      scenarios.slice(0, 2).map((scenario) => (
                        <Badge key={scenario} severity="neutral">
                          {scenarioMeta(scenario).label}
                        </Badge>
                      ))
                    )}
                    {scenarios.length > 2 && (
                      <span className="text-2xs text-fg-subtle">+{scenarios.length - 2}</span>
                    )}
                  </span>
                </Td>
                <Td>
                  {item.config.defense_enabled ? (
                    <Badge severity="ok">On</Badge>
                  ) : (
                    <Badge severity="warn">Off</Badge>
                  )}
                </Td>
                <Td className="whitespace-nowrap">
                  {item.final_status ?? <span className="text-fg-subtle">in flight</span>}
                  {item.final_sim_tick !== null && (
                    <span className="ml-1.5 font-mono text-2xs text-fg-subtle">
                      t{item.final_sim_tick}
                    </span>
                  )}
                </Td>
                <Td>
                  {item.is_complete === true ? (
                    <Badge severity="ok">Complete</Badge>
                  ) : (
                    <Badge
                      severity="warn"
                      title="A gap was detected in this run's persisted event log, or it was never finalized"
                    >
                      Incomplete
                    </Badge>
                  )}
                </Td>
                <Td className="text-right">
                  <Link
                    href={`/history/${item.experiment_id}`}
                    className="text-2xs font-medium text-accent transition-colors hover:text-accent-hover"
                  >
                    Replay →
                  </Link>
                </Td>
              </Tr>
            );
          })}
        </tbody>
      </TableWrap>

      {nextCursor && (
        <div className="border-t border-line px-4 py-3">
          <Button size="sm" onClick={() => void loadMore()} disabled={loading}>
            {loading ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
    </>
  );
}

export default function HistoryPage() {
  const [status, setStatus] = useState<StatusFilter>("all");
  const [defenseEnabled, setDefenseEnabled] = useState<DefenseFilter>("all");
  // Selection for comparison -- at most two, FIFO eviction on a third pick,
  // deliberately a plain list rather than a Set for stable A/B ordering.
  const [selected, setSelected] = useState<string[]>([]);

  function toggleSelect(id: string) {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 2) return [prev[1], id];
      return [...prev, id];
    });
  }

  return (
    <div className="flex flex-col">
      <PageHeader
        eyebrow="Archive"
        title="Runs"
        description="Every assessment is persisted event by event while it runs. Replay any of them deterministically, or select two to compare."
        actions={
          selected.length === 2 ? (
            <ButtonLink
              variant="primary"
              href={`/history/compare?a=${selected[0]}&b=${selected[1]}`}
            >
              Compare selected
            </ButtonLink>
          ) : (
            <span className="text-2xs text-fg-subtle">
              Select two runs to compare {selected.length === 1 && "(1 selected)"}
            </span>
          )
        }
      />

      <div className="p-4 lg:p-5">
        <Panel flush>
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-3 py-2">
            <SegmentedControl
              ariaLabel="Filter by outcome"
              value={status}
              onChange={setStatus}
              options={STATUS_OPTIONS}
            />
            <SegmentedControl
              ariaLabel="Filter by defense posture"
              value={defenseEnabled}
              onChange={setDefenseEnabled}
              options={DEFENSE_OPTIONS}
            />
            {selected.length > 0 && (
              <div className="ml-auto flex items-center gap-1.5">
                {selected.map((id, index) => (
                  <ConfigChip key={id} label={index === 0 ? "A" : "B"} value={shortId(id)} />
                ))}
                <Button size="sm" variant="ghost" onClick={() => setSelected([])}>
                  Clear
                </Button>
              </div>
            )}
          </div>

          <HistoryList
            key={`${status}-${defenseEnabled}`}
            status={status}
            defenseEnabled={defenseEnabled}
            selected={selected}
            onToggleSelect={toggleSelect}
          />
        </Panel>
      </div>
    </div>
  );
}
