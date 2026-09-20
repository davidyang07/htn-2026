import { Panel, PanelHeader } from "@/components/ui/Panel";
import { EmptyState } from "@/components/ui/States";
import { cn } from "@/lib/cn";
import type { ArtifactView } from "@/lib/runtime/client";
import type { Incident } from "@/lib/runtime/incident";

/**
 * How containment actually worked, as a chain rather than a property list.
 *
 * The product's payoff is not "a worker was quarantined" — it is that the
 * quarantined worker's *output* was discarded, a genuinely new worker took
 * the task, and that new worker was seeded from trusted artifacts only. Those
 * are three links of one chain, and reading them as three unrelated rows in a
 * definition list is what made the recovery look like bookkeeping.
 *
 * Every link is drawn only when the event that proves it has arrived, so a
 * partially-recovered run shows a genuinely partial chain rather than an
 * optimistic one.
 */
export function ContainmentPanel({
  incident,
  artifacts,
}: {
  incident: Incident;
  artifacts: readonly ArtifactView[];
}) {
  if (!incident.detected) {
    return (
      <Panel>
        <PanelHeader
          title="Containment"
          description="What happens to the compromised worker's work."
        />
        <EmptyState
          compact
          title="Nothing to contain"
          description="No worker has been quarantined, so no output has been discarded."
        />
      </Panel>
    );
  }

  const tainted = artifacts.filter((a) => !a.trusted);
  const trustedContext = artifacts.filter((a) => incident.trustedContextIds.includes(a.id));

  return (
    <Panel>
      <PanelHeader
        title="Containment"
        description="The compromised worker stayed out, and its work went with it."
      />

      <ol className="flex flex-col">
        <Link
          severity="critical"
          title={incident.workerRole ?? incident.workerId ?? "The worker"}
          subtitle={incident.workerId ?? undefined}
          badge="Quarantined"
        >
          Removed from the team. Every later request it makes is refused on sight, whatever
          the path.
        </Link>

        <Connector label="output discarded" tone="critical" />

        <Link
          severity="critical"
          title="Tainted output"
          badge={`${incident.taintedArtifactIds.length} artifact${
            incident.taintedArtifactIds.length === 1 ? "" : "s"
          }`}
        >
          {tainted.length === 0 ? (
            "No artifact was marked untrusted."
          ) : (
            <>
              {tainted.map((artifact) => (
                <span key={artifact.id} className="mr-2 font-mono text-2xs">
                  {artifact.id}
                </span>
              ))}
              — excluded from every downstream worker&rsquo;s context.
            </>
          )}
        </Link>

        <Connector label="task reassigned" tone="contained" />

        {incident.replacementWorkerId ? (
          <Link
            severity="ok"
            title={incident.replacementRole ?? incident.replacementWorkerId}
            subtitle={incident.replacementWorkerId}
            badge="New worker"
          >
            {incident.trustedContextOnly ? (
              <>
                A distinct worker with its own identity, started under a{" "}
                <span className="font-mono text-2xs">trusted_artifacts_only</span> context
                policy — seeded with{" "}
                {trustedContext.length > 0
                  ? trustedContext.map((a) => a.id).join(", ")
                  : incident.trustedContextIds.join(", ") || "no artifacts"}{" "}
                and nothing the quarantined worker produced.
              </>
            ) : (
              "A distinct worker with its own identity took over the task."
            )}
          </Link>
        ) : (
          <Link severity="neutral" title="Replacement" badge="Pending">
            No replacement worker has been created yet.
          </Link>
        )}
      </ol>
    </Panel>
  );
}

const SEVERITY_RAIL = {
  critical: "border-critical/40 bg-critical-soft",
  contained: "border-contained/40 bg-contained-soft",
  ok: "border-ok/40 bg-ok-soft",
  neutral: "border-line bg-raised",
} as const;

const SEVERITY_LABEL = {
  critical: "text-critical",
  contained: "text-contained",
  ok: "text-ok",
  neutral: "text-fg-subtle",
} as const;

type Tone = keyof typeof SEVERITY_RAIL;

function Link({
  severity,
  title,
  subtitle,
  badge,
  children,
}: {
  severity: Tone;
  title: string;
  subtitle?: string;
  badge: string;
  children: React.ReactNode;
}) {
  return (
    <li className={cn("rounded-md border px-3 py-2.5", SEVERITY_RAIL[severity])}>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className={cn("text-xs font-semibold", SEVERITY_LABEL[severity])}>{title}</span>
        {subtitle && <span className="font-mono text-2xs text-fg-subtle">{subtitle}</span>}
        <span
          className={cn(
            "ml-auto shrink-0 text-2xs font-semibold uppercase tracking-wide",
            SEVERITY_LABEL[severity],
          )}
        >
          {badge}
        </span>
      </div>
      <p className="mt-1 text-2xs leading-4 text-fg-muted">{children}</p>
    </li>
  );
}

/** The vertical join between two links, labelled with what it represents. */
function Connector({ label, tone }: { label: string; tone: Tone }) {
  return (
    <li aria-hidden className="flex items-center gap-2 py-1 pl-3">
      <span
        className={cn(
          "block h-4 w-px",
          tone === "critical" ? "bg-critical/40" : "bg-contained/50",
        )}
      />
      <span className={cn("text-2xs font-medium", SEVERITY_LABEL[tone])}>{label}</span>
    </li>
  );
}
