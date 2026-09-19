import { SeverityDot } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";
import { formatEventMetadata } from "@/lib/format";
import { SEVERITY_TEXT } from "@/lib/severity";
import type { Event } from "@/lib/stream/reducer";
import { eventMeta, eventSeverity } from "@/lib/vocabulary";

/**
 * One line of the event log. Reads as a sentence — *when*, *what*, *between
 * whom* — with the machine event type kept alongside the human label so the
 * log is still greppable against the backend's schema.
 */
export function EventRow({
  event,
  compact,
  onSelectAgent,
}: {
  event: Event;
  compact?: boolean;
  onSelectAgent?: (agentId: string) => void;
}) {
  const meta = eventMeta(event.event_type);
  const severity = eventSeverity(event.event_type, event.metadata ?? null);
  const metadata = formatEventMetadata(event.metadata as Record<string, unknown> | null);
  const source = event.source_agent_id ?? event.agent_id ?? null;
  const target = event.target_agent_id ?? null;

  return (
    <li className={cn("flex items-baseline gap-2.5", compact ? "py-1" : "py-1.5")}>
      <span className="flex w-10 shrink-0 items-baseline gap-1.5">
        <SeverityDot severity={severity} className="translate-y-[-1px]" />
        <span className="font-mono text-2xs tabular text-fg-subtle">t{event.sim_tick}</span>
      </span>

      <span className={cn("shrink-0 text-2xs font-medium", SEVERITY_TEXT[severity])}>
        {meta.label}
      </span>

      {(source || target) && (
        <span
          className={cn(
            "truncate font-mono text-2xs text-fg-muted",
            // Compact rows live in a narrow side panel and must give way; the
            // full-width log keeps ids intact and lets metadata truncate instead.
            compact ? "min-w-0 flex-1" : "shrink-0",
          )}
        >
          {source && (
            <ClickableId id={source} onSelect={onSelectAgent} />
          )}
          {source && target && <span className="text-fg-subtle"> → </span>}
          {target && <ClickableId id={target} onSelect={onSelectAgent} />}
        </span>
      )}

      {metadata && !compact && (
        <span className="ml-auto min-w-0 flex-1 truncate text-right font-mono text-2xs text-fg-subtle">
          {metadata}
        </span>
      )}
    </li>
  );
}

function ClickableId({ id, onSelect }: { id: string; onSelect?: (id: string) => void }) {
  if (!onSelect) return <span>{id}</span>;
  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      className="rounded-xs transition-colors hover:text-accent"
    >
      {id}
    </button>
  );
}
