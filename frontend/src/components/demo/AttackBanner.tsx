import { IconAlert, IconShieldCheck } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import type { Incident } from "@/lib/runtime/incident";

/**
 * The moment the product exists for.
 *
 * A worker asked for something outside its policy envelope and was refused
 * synchronously — before any content was read. That is one causal chain, so
 * it is drawn as one: the path it wanted, then the four beats that followed,
 * in the order the backend emitted them.
 *
 * The path is the largest type on the screen after the run state, because
 * "it wanted *this*, and did not get it" is the entire claim. There is no
 * content to show beside it and there never will be — nothing opened the file.
 */
export function AttackBanner({ incident }: { incident: Incident }) {
  if (!incident.detected) return <QuietState />;

  return (
    <div className="overflow-hidden rounded-lg border border-critical/40 bg-critical-soft">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-critical/25 px-5 py-3">
        <IconAlert className="size-4 shrink-0 text-critical" />
        <h3 className="text-sm font-semibold tracking-tight text-critical">
          Protected resource blocked
        </h3>
        {incident.rule && (
          <span className="rounded-sm bg-critical/15 px-1.5 py-0.5 font-mono text-2xs text-critical ring-1 ring-inset ring-critical/30">
            {incident.rule}
          </span>
        )}
        <p className="ml-auto min-w-0 truncate text-2xs text-critical/80">
          {incident.workerRole ?? incident.workerId} requested it and was refused
        </p>
      </div>

      <div className="flex flex-col gap-4 px-5 py-4">
        <div className="min-w-0">
          <p className="eyebrow mb-1 text-critical/70">Requested path</p>
          <p className="break-all font-mono text-base font-medium leading-6 text-critical">
            {incident.resource}
          </p>
        </div>

        <ol className="flex flex-wrap items-stretch gap-x-1 gap-y-2">
          {incident.cascade.map((step, index) => (
            <li key={step.key} className="flex min-w-0 items-stretch">
              {index > 0 && (
                <span aria-hidden className="self-center px-1.5 text-critical/40">
                  →
                </span>
              )}
              <div
                className={cn(
                  "min-w-0 rounded-md border px-2.5 py-1.5",
                  step.seq === null
                    ? "border-line bg-surface/40"
                    : "border-critical/30 bg-critical/10",
                )}
              >
                <p
                  className={cn(
                    "truncate text-2xs font-semibold uppercase tracking-wide",
                    step.seq === null ? "text-fg-subtle" : "text-critical",
                  )}
                >
                  {step.label}
                </p>
                <p
                  className="truncate text-2xs text-fg-subtle"
                  title={step.detail || undefined}
                >
                  {step.seq === null ? "not reached" : step.detail}
                </p>
              </div>
            </li>
          ))}
        </ol>

        {incident.reason && (
          <p className="text-xs leading-5 text-critical/85">{incident.reason}</p>
        )}

        <p className="text-2xs leading-4 text-fg-subtle">
          The decision was made synchronously by a deterministic path policy and every event
          above was recorded before the request returned. The path is shown; the file
          was never opened, so there is no content to show.
        </p>
      </div>
    </div>
  );
}

/** Before any violation. Calm, and explicit about what would appear here. */
function QuietState() {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-line bg-surface px-5 py-4">
      <IconShieldCheck className="size-4 shrink-0 text-ok" />
      <div className="min-w-0">
        <p className="text-sm font-medium text-fg">No policy violation yet</p>
        <p className="text-xs text-fg-subtle">
          Every resource request so far has been inside the sandbox. The moment one is not,
          the path it asked for appears here.
        </p>
      </div>
    </div>
  );
}
