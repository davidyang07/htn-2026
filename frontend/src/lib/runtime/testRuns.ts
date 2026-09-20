// The regression suite, before the fix and after it.
//
// The demo runs `pytest demo_target` twice against the same test file: once
// against the vulnerable module, where it must fail, and once against the
// patched one, where it must pass. That pair is the evidence the user's task
// actually asked for — a suite that was always green proves nothing about a
// vulnerability — and the previous UI kept only the last run, so the red one
// was invisible.
//
// Counts are parsed from pytest's own summary line and never assembled from
// anywhere else. When a line cannot be parsed, the verbatim line is still
// shown and no counts are claimed: `passed` comes from the recorded exit
// code, which is the authority, not from the text.

import type { Event } from "@/lib/stream/reducer";

export type TestCount = { label: string; value: number };

export type TestRun = {
  /** Sequence number of the TASK_COMPLETED that recorded it. */
  seq: number;
  workerId: string | null;
  /** From the recorded exit code. A red run is red. */
  passed: boolean;
  /** pytest's own summary line, verbatim. */
  summary: string;
  /** The command as recorded, e.g. "pytest demo_target". */
  command: string | null;
  exitCode: number | null;
  /** Counts parsed out of the summary line, in pytest's own order. */
  counts: readonly TestCount[];
};

export type TestEvidence = {
  runs: readonly TestRun[];
  /** The first recorded run. */
  before: TestRun | null;
  /** The last recorded run, when more than one exists. */
  after: TestRun | null;
  /** True when the first run failed: the vulnerability was reproduced. */
  provedRed: boolean;
  /** True when the last run passed and there was an earlier one to compare. */
  provedGreen: boolean;
};

export const EMPTY_TEST_EVIDENCE: TestEvidence = {
  runs: [],
  before: null,
  after: null,
  provedRed: false,
  provedGreen: false,
};

const COUNT_RE = /(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected)/gi;

/** pytest's own words, split into countable parts. Nothing is inferred. */
export function parseCounts(summary: string): TestCount[] {
  const counts: TestCount[] = [];
  for (const match of summary.matchAll(COUNT_RE)) {
    const value = Number(match[1]);
    if (!Number.isFinite(value)) continue;
    counts.push({ label: match[2]!.toLowerCase(), value });
  }
  return counts;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function deriveTestEvidence(events: readonly Event[]): TestEvidence {
  const runs: TestRun[] = [];

  for (const event of events) {
    if (event.event_type !== "TASK_COMPLETED") continue;
    const meta = (event.metadata ?? {}) as Record<string, unknown>;
    if (meta["step"] !== "pytest") continue;

    const summary = str(meta["detail"]) ?? "";
    runs.push({
      seq: event.seq,
      workerId: event.agent_id ?? null,
      // The only thing that makes this true is a run that reported passed.
      passed: meta["passed"] === true,
      summary,
      command: str(meta["command"]),
      exitCode: typeof meta["exit_code"] === "number" ? meta["exit_code"] : null,
      counts: parseCounts(summary),
    });
  }

  if (runs.length === 0) return EMPTY_TEST_EVIDENCE;

  const before = runs[0]!;
  // A single run is not a before/after pair, and presenting it as one would
  // claim a comparison that was never made.
  const after = runs.length > 1 ? runs[runs.length - 1]! : null;

  return {
    runs,
    before,
    after,
    provedRed: !before.passed,
    provedGreen: after !== null && after.passed,
  };
}
