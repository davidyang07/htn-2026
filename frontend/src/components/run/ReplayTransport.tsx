"use client";

import type { Dispatch } from "react";

import { Button, SegmentedControl } from "@/components/ui/Button";
import { IconPause, IconPlay, IconRestart } from "@/components/ui/icons";
import type { ReplayControlAction, ReplayControlState } from "@/lib/replay/controlReducer";

const SPEED_OPTIONS = [0.25, 0.5, 1, 2, 4, 8] as const;

/**
 * Replay transport. Visually mirrors the live run-context bar, but wired to
 * local playback state — replay is driven entirely from a prefetched event
 * log, so none of these actions costs a network round-trip.
 */
export function ReplayTransport({
  control,
  dispatch,
  totalEvents,
  playedCount,
  onSeek,
  tick,
}: {
  control: ReplayControlState;
  dispatch: Dispatch<ReplayControlAction>;
  totalEvents: number;
  playedCount: number;
  onSeek: (index: number) => void;
  tick: number;
}) {
  const finished = totalEvents > 0 && playedCount >= totalEvents;
  const progress = totalEvents > 0 ? playedCount / totalEvents : 0;

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface px-4 py-2">
      <Button
        size="sm"
        variant="primary"
        onClick={() => dispatch({ type: "toggle_play" })}
        disabled={totalEvents === 0 || finished}
      >
        {control.playing ? (
          <>
            <IconPause className="size-3.5" /> Pause
          </>
        ) : (
          <>
            <IconPlay className="size-3.5" /> Play
          </>
        )}
      </Button>

      <Button
        size="sm"
        onClick={() => {
          dispatch({ type: "pause" });
          onSeek(0);
        }}
        disabled={totalEvents === 0}
      >
        <IconRestart className="size-3.5" />
        Restart
      </Button>

      <SegmentedControl
        ariaLabel="Replay speed"
        value={control.speed}
        onChange={(speed) => dispatch({ type: "set_speed", speed })}
        options={SPEED_OPTIONS.map((m) => ({ value: m, label: `${m}×` }))}
      />

      <div className="relative flex min-w-48 flex-1 items-center">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 overflow-hidden rounded-full bg-line"
        >
          <div className="h-full rounded-full bg-accent" style={{ width: `${progress * 100}%` }} />
        </div>
        <input
          type="range"
          min={0}
          max={totalEvents}
          value={playedCount}
          onChange={(e) => onSeek(Number(e.target.value))}
          disabled={totalEvents === 0}
          aria-label="Scrub replay position"
          className="relative z-10 h-4 w-full cursor-pointer appearance-none bg-transparent
            [&::-moz-range-thumb]:size-3 [&::-moz-range-thumb]:cursor-pointer [&::-moz-range-thumb]:rounded-full
            [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-fg
            [&::-webkit-slider-thumb]:size-3 [&::-webkit-slider-thumb]:appearance-none
            [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-fg
            [&::-webkit-slider-thumb]:shadow-panel"
        />
      </div>

      <span className="shrink-0 font-mono text-2xs tabular text-fg-muted">
        tick {tick} · event {playedCount}
        <span className="text-fg-subtle">/{totalEvents}</span>
      </span>
    </div>
  );
}
