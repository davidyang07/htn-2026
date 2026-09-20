import { SeverityDot } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";
import type { ModelProvenance } from "@/lib/runtime/provenance";
import type { StageNode } from "@/lib/runtime/stage";
import {
  SECURITY_STATE_LABEL,
  SECURITY_STATE_SEVERITY,
  SEVERITY_TEXT,
  type SecurityState,
  type Severity,
} from "@/lib/severity";

/**
 * One worker on the incident stage.
 *
 * The card carries its state in its own chrome — border, ground, and a single
 * status line — rather than in a badge bolted to a neutral box, so the
 * compromised worker is unmistakable at a glance and the healthy ones stay
 * quiet. Colour comes from `severity.ts` and means security state only.
 *
 * This replaced a separate worker table that repeated role, id, state and
 * model-backing for every node already on the stage. A judge should not have
 * to read the same five rows twice.
 */

/**
 * On this screen a quarantined worker *is* the breach, so it reads critical
 * rather than the product-wide `contained` purple. The deviation is confined
 * to the stage: purple still means containment everywhere it appears here,
 * and it is what the reassignment drop and the incident badges use.
 */
const STAGE_SEVERITY: Record<SecurityState, Severity> = {
  ...SECURITY_STATE_SEVERITY,
  quarantined: "critical",
};

const STATE_SHELL: Record<SecurityState, string> = {
  healthy: "border-line bg-raised",
  suspicious: "border-warn/35 bg-warn-soft",
  compromised: "border-critical/45 bg-critical-soft",
  quarantined: "border-critical/55 bg-critical-soft",
  recovered: "border-ok/35 bg-ok-soft",
};

export function WorkerNode({
  node,
  provenance,
}: {
  node: StageNode;
  provenance: ModelProvenance | null;
}) {
  const severity = STAGE_SEVERITY[node.securityState];
  const quarantined = node.securityState === "quarantined";

  // One line, and only one: why it is out, or what it is on. A quarantined
  // worker's reason always wins — it is the more important fact about it.
  const note = quarantined ? node.quarantineReason : node.currentTask;

  return (
    <article
      className={cn(
        "flex min-w-0 flex-col gap-2.5 rounded-lg border p-3.5 transition-colors duration-300",
        STATE_SHELL[node.securityState],
      )}
    >
      <header className="flex min-w-0 items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3
            className={cn(
              "truncate text-sm font-semibold tracking-tight",
              quarantined ? "text-critical" : "text-fg",
            )}
            title={node.role}
          >
            {node.role}
          </h3>
          <p className="truncate font-mono text-2xs text-fg-subtle" title={node.id}>
            {node.id}
          </p>
        </div>
        {node.replaces && (
          <span
            className="shrink-0 rounded-sm bg-contained-soft px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide text-contained ring-1 ring-inset ring-contained/25"
            title={`Created mid-run to take over from ${node.replaces}`}
          >
            New
          </span>
        )}
      </header>

      <p className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide">
        <SeverityDot severity={severity} />
        <span className={SEVERITY_TEXT[severity]}>
          {SECURITY_STATE_LABEL[node.securityState]}
        </span>
      </p>

      {note && (
        <p
          className={cn(
            "line-clamp-2 text-2xs leading-4",
            quarantined ? "text-critical/85" : "text-fg-muted",
          )}
          title={note}
        >
          {note}
        </p>
      )}

      <p
        className="min-w-0 truncate border-t border-line/60 pt-2 font-mono text-2xs text-fg-subtle"
        title={provenanceTitle(provenance)}
      >
        {provenance ? (
          <>
            {provenance.model}
            <span className="text-fg-subtle/70"> · {provenance.provider}</span>
          </>
        ) : (
          // Never imply a model ran when none was recorded for this worker.
          <span className="text-fg-subtle/70">no model call recorded</span>
        )}
      </p>
    </article>
  );
}

function provenanceTitle(provenance: ModelProvenance | null): string | undefined {
  if (!provenance) return undefined;
  return `${provenance.calls} call(s) to ${provenance.endpointHost}${
    provenance.route ? ` via the ${provenance.route} route` : ""
  }`;
}
