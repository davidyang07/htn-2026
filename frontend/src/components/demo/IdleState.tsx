import { BrandMark } from "@/components/ui/icons";
import { cn } from "@/lib/cn";

/**
 * The screen before there is anything to show.
 *
 * A live session is created by a WorkSwarm run that has not been launched
 * yet, so this state is on screen for as long as it takes someone to switch
 * terminals — which at a demo is exactly when a judge first looks at it. It
 * therefore says what is about to happen rather than "no data", and carries
 * the command that makes it happen.
 *
 * Nothing here is a preview of results. The three beats are the shape of the
 * run, stated as intent; no number, path or verdict appears until an event
 * carries one.
 */

const BEATS = [
  {
    step: "01",
    title: "A real team starts work",
    body: "Five WorkSwarm workers register and take a real repository task.",
  },
  {
    step: "02",
    title: "One of them is compromised",
    body: "An indirect prompt injection makes a worker reach outside its policy envelope. AgentShield refuses it before anything is read, and quarantines it.",
  },
  {
    step: "03",
    title: "The swarm routes around it",
    body: "The tainted output is discarded, a new worker takes the task on trusted context only, and the job still finishes — proven by a real test run.",
  },
];

export function IdleState({
  status,
  detail,
  command,
}: {
  status: "waiting" | "connecting" | "unreachable";
  detail?: string | null;
  command: string;
}) {
  const unreachable = status === "unreachable";

  return (
    <div
      className={cn(
        "flex flex-col gap-6 rounded-lg border bg-surface px-6 py-8 sm:px-10 sm:py-12",
        unreachable ? "border-critical/35" : "border-line",
      )}
    >
      <header className="flex flex-col items-center gap-3 text-center">
        <BrandMark className={cn("size-7", unreachable ? "text-critical" : "text-accent")} />
        <h2 className="text-xl font-semibold tracking-tight text-fg">
          {unreachable
            ? "Cannot reach the AgentShield control plane"
            : status === "connecting"
              ? "Attaching to the live session…"
              : "Ready for a live run"}
        </h2>
        <p className="max-w-xl text-xs leading-5 text-fg-muted">
          {unreachable ? (
            <>
              The backend is not answering, so this screen has nothing to attach to. Start it,
              and check that the frontend is pointed at the port it is listening on.
            </>
          ) : status === "connecting" ? (
            <>A session exists. Reading its snapshot and replaying its events.</>
          ) : (
            <>
              This screen attaches to the WorkSwarm session the moment one is created, and
              narrates it as it happens. Nothing below is filled in until an event fills it.
            </>
          )}
        </p>
      </header>

      {unreachable ? (
        <div className="mx-auto w-full max-w-xl">
          {detail && (
            <p className="break-words rounded-md border border-critical/25 bg-critical-soft px-3 py-2 font-mono text-2xs leading-4 text-critical/90">
              {detail}
            </p>
          )}
          <p className="mt-3 text-2xs leading-4 text-fg-subtle">
            AgentShield and WorkSwarm both default to port 8000, so the documented local setup
            puts AgentShield on 8100 and points{" "}
            <span className="font-mono">NEXT_PUBLIC_BACKEND_URL</span> at it.
          </p>
        </div>
      ) : (
        <ol className="grid gap-4 sm:grid-cols-3">
          {BEATS.map((beat) => (
            <li
              key={beat.step}
              className="flex min-w-0 flex-col gap-1.5 rounded-md border border-line bg-raised p-4"
            >
              <span className="font-mono text-2xs tabular text-fg-subtle/70">{beat.step}</span>
              <h3 className="text-xs font-semibold text-fg">{beat.title}</h3>
              <p className="text-2xs leading-4 text-fg-subtle">{beat.body}</p>
            </li>
          ))}
        </ol>
      )}

      {status === "waiting" && (
        <div className="flex flex-col items-center gap-2">
          <p className="eyebrow">Launch it with</p>
          <code className="rounded-md border border-line-strong bg-raised px-3 py-2 font-mono text-xs text-fg">
            {command}
          </code>
          <p className="text-2xs text-fg-subtle">
            Polling for a session — this screen picks it up on its own.
          </p>
        </div>
      )}
    </div>
  );
}
