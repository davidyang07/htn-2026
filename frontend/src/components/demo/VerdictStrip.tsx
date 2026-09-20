import { cn } from "@/lib/cn";
import type { VerdictLight } from "@/lib/runtime/verdict";

/**
 * The conclusion of the story.
 *
 * Four claims, each lit by exactly one recorded event and by nothing else —
 * `verdictLights` is where that mapping lives, and the strip renders it
 * without adding a rule of its own. A light that can be set by anything other
 * than the event it names is a light that can lie.
 *
 * Unreached claims sit quiet rather than broken: mid-run, half this strip is
 * legitimately not true yet, and a screen that renders "not yet" as a failure
 * teaches a judge to distrust the half that is true.
 */
export function VerdictStrip({ lights }: { lights: VerdictLight[] }) {
  const complete = lights.every((light) => light.status === "lit");
  const failed = lights.some((light) => light.status === "failed");

  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border transition-colors duration-500",
        failed
          ? "border-critical/40 bg-critical-soft"
          : complete
            ? "border-ok/40 bg-ok-soft"
            : "border-line bg-surface",
      )}
    >
      <ul className="grid divide-line/60 sm:grid-cols-2 sm:divide-x xl:grid-cols-4">
        {lights.map((light) => (
          <li
            key={light.key}
            className="flex min-w-0 items-start gap-2.5 border-b border-line/60 px-4 py-3.5 last:border-b-0 sm:border-b-0"
          >
            <Mark status={light.status} />
            <div className="min-w-0 flex-1">
              <p
                className={cn(
                  "truncate text-xs font-bold uppercase tracking-[0.1em]",
                  light.status === "lit"
                    ? "text-ok"
                    : light.status === "failed"
                      ? "text-critical"
                      : "text-fg-subtle",
                )}
              >
                {light.label}
              </p>
              <p
                className="mt-0.5 line-clamp-2 text-2xs leading-4 text-fg-subtle"
                title={light.hint}
              >
                {light.hint}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Check when proven, cross when disproven, hollow ring while unresolved. */
function Mark({ status }: { status: VerdictLight["status"] }) {
  return (
    <svg
      aria-hidden
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      className={cn(
        "mt-px size-4 shrink-0",
        status === "lit"
          ? "text-ok"
          : status === "failed"
            ? "text-critical"
            : "text-fg-subtle/50",
      )}
    >
      <circle
        cx="8"
        cy="8"
        r="6.5"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeDasharray={status === "pending" ? "2 2.5" : undefined}
      />
      {status === "lit" && (
        <path
          d="m5.2 8.2 2 2 3.6-4.2"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
      {status === "failed" && (
        <path
          d="m5.8 5.8 4.4 4.4M10.2 5.8l-4.4 4.4"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      )}
    </svg>
  );
}
