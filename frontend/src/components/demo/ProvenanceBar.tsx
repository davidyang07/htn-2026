import { cn } from "@/lib/cn";
import {
  routeLabel,
  type ModelProvenance,
  type ProvenanceIndex,
} from "@/lib/runtime/provenance";

/**
 * Who actually answered, in one line under the stage.
 *
 * Provenance matters and is not the point of the screen, so it is sized like
 * a footnote and reads like one. Every figure is counted from MODEL_REQUESTED
 * events, which exist only when a real call was made: a run with deterministic
 * stand-ins says so instead of quietly naming a model that never ran.
 */
export function ProvenanceBar({ provenance }: { provenance: ProvenanceIndex }) {
  if (provenance.calls === 0) {
    return (
      <p className="px-1 text-2xs leading-4 text-fg-subtle">
        No model call was recorded in this run — every worker ran as a deterministic stand-in.
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-1 text-2xs text-fg-subtle">
      <span>
        <span className="font-mono tabular text-fg-muted">{provenance.calls}</span> real model
        call{provenance.calls === 1 ? "" : "s"}
      </span>

      {provenance.distinct.map((model) => (
        <ModelChip key={`${model.model}@${model.endpointHost}`} model={model} />
      ))}

      {provenance.fallbacks.map((fallback) => (
        <span key={fallback.workerId} className="text-warn/80">
          <span className="font-mono">{fallback.workerId}</span> took the{" "}
          <span className="font-mono">{routeLabel(fallback.route)}</span> route
        </span>
      ))}

      <span className="min-w-0">
        Identity and timing only — no prompt, completion or credential leaves the worker.
      </span>
    </div>
  );
}

function ModelChip({ model }: { model: ModelProvenance }) {
  return (
    <span
      className={cn("inline-flex items-baseline gap-1.5")}
      title={`${model.calls} call(s) to ${model.endpointHost}`}
    >
      <span className="font-mono text-fg-muted">{model.model}</span>
      <span aria-hidden>·</span>
      <span>{model.provider}</span>
    </span>
  );
}
