"use client";

import Link from "next/link";

import { Badge, ConfigChip, RunStatusBadge } from "@/components/ui/Badge";
import { Button, SegmentedControl } from "@/components/ui/Button";
import { BrandMark, IconPause, IconPlay, IconRestart } from "@/components/ui/icons";
import { Spinner } from "@/components/ui/States";
import { useExperiment } from "@/lib/experiment/ExperimentProvider";
import { shortId } from "@/lib/format";

const SPEED_OPTIONS = [0.25, 0.5, 1, 2, 4, 8] as const;

/**
 * Always-visible answer to "what am I looking at, and is it still moving?".
 * The transport controls live here rather than on any one screen because they
 * apply to the run, not to a view of it.
 */
export function RunContextBar() {
  const {
    control,
    stream,
    schemaError,
    hydrating,
    canPause,
    canResume,
    canReset,
    canSetSpeed,
    pause,
    resume,
    reset,
    changeSpeed,
  } = useExperiment();

  const config = control.activeConfig;
  const progress = config ? Math.min(1, stream.tick / config.max_ticks) : 0;

  return (
    <div className="shrink-0 border-b border-line bg-surface">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2 lg:px-4">
        <Link href="/" className="flex items-center gap-2 text-fg lg:hidden">
          <BrandMark className="text-accent" />
          <span className="text-sm font-semibold tracking-tight">AgentShield</span>
        </Link>

        {hydrating ? (
          <span className="flex items-center gap-2 text-xs text-fg-muted">
            <Spinner /> Restoring session…
          </span>
        ) : control.experimentId && config ? (
          <>
            <div className="flex min-w-0 items-center gap-2.5">
              <RunStatusBadge status={control.status} />
              <span
                className="hidden font-mono text-2xs text-fg-subtle sm:inline"
                title={control.experimentId}
              >
                {shortId(control.experimentId)}
              </span>
            </div>

            <div className="flex min-w-32 max-w-56 flex-1 items-center gap-2">
              <div className="h-1 min-w-0 flex-1 overflow-hidden rounded-full bg-line">
                <div
                  className="h-full rounded-full bg-accent transition-[width] duration-300"
                  style={{ width: `${progress * 100}%` }}
                />
              </div>
              <span className="shrink-0 font-mono text-2xs tabular text-fg-muted">
                t{stream.tick}
                <span className="text-fg-subtle">/{config.max_ticks}</span>
              </span>
            </div>

            <div className="hidden items-center gap-1.5 xl:flex">
              <ConfigChip label="seed" value={config.seed} />
              <ConfigChip label="agents" value={config.node_count} />
              <ConfigChip label="defense" value={config.defense_enabled ? "on" : "off"} />
            </div>

            <div className="ml-auto flex items-center gap-2">
              {control.status === "paused" ? (
                <Button size="sm" onClick={resume} disabled={!canResume}>
                  <IconPlay className="size-3.5" />
                  Resume
                </Button>
              ) : (
                <Button size="sm" onClick={pause} disabled={!canPause}>
                  <IconPause className="size-3.5" />
                  Pause
                </Button>
              )}
              <Button
                size="sm"
                onClick={reset}
                disabled={!canReset}
                title="Stop this run and start an identical one from the same seed"
              >
                <IconRestart className="size-3.5" />
                Re-run
              </Button>
              <SegmentedControl
                ariaLabel="Playback speed"
                value={control.speed}
                disabled={!canSetSpeed}
                onChange={changeSpeed}
                options={SPEED_OPTIONS.map((m) => ({ value: m, label: `${m}×` }))}
                className="hidden sm:inline-flex"
              />
            </div>
          </>
        ) : (
          <>
            <Badge severity="neutral">No active assessment</Badge>
            <span className="hidden text-xs text-fg-subtle sm:inline">
              Configure a system and launch a run to begin.
            </span>
            <div className="ml-auto">
              <Link
                href="/"
                className="text-xs font-medium text-accent transition-colors hover:text-accent-hover"
              >
                Go to launch →
              </Link>
            </div>
          </>
        )}
      </div>

      {(control.error || schemaError) && (
        <p
          role="alert"
          className="border-t border-critical/25 bg-critical-soft px-4 py-1.5 text-2xs text-critical"
        >
          {schemaError ?? control.error}
        </p>
      )}
    </div>
  );
}
