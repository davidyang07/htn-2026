"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { IconChevronDown, IconChevronRight } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import type { IncidentExplanation } from "@/lib/runtime/client";

/**
 * Post-hoc commentary, labelled as commentary.
 *
 * This panel is the one place on the screen where a model wrote the words, so
 * it says so twice: in its header, and in a standing note that the security
 * decision was made without it. It sits after the deterministic evidence for
 * the same reason — nothing here is allowed to read as the reason anything
 * was blocked.
 *
 * The five evidence-backed sections are rendered as sections rather than as
 * the single wall of prose the API also returns, and only the first is open,
 * because a paragraph nobody reads is worse than a heading they do.
 */

const SECTION_ORDER = [
  ["what_happened", "What happened"],
  ["why_blocked", "Why AgentShield blocked it"],
  ["what_was_contained", "What was contained"],
  ["how_swarm_recovered", "How the swarm recovered"],
  ["recovery_evidence", "What proves recovery worked"],
] as const;

const AUTHORITY_NOTE =
  "Security enforcement was deterministic. This explanation did not make the quarantine " +
  "decision and cannot change it — it was written from events that were already recorded.";

export function ExplanationPanel({
  explanation,
}: {
  explanation: IncidentExplanation | null;
}) {
  if (!explanation?.available) {
    return (
      <Panel>
        <PanelHeader
          title="Incident explanation"
          description="Written once an incident exists, and never before one."
        />
        <p className="text-xs text-fg-subtle">
          No incident has been recorded yet, so there is nothing to explain.
        </p>
        <p className="mt-3 text-2xs leading-4 text-fg-subtle">{AUTHORITY_NOTE}</p>
      </Panel>
    );
  }

  const generated =
    explanation.source === "openai"
      ? `AI-generated · ${explanation.model ?? "model"}${
          explanation.provider ? ` · ${explanation.provider}` : ""
        }`
      : "Generated locally from recorded events — no model involved";

  return (
    <Panel>
      {/* No panel title: the section above is already called "The
          explanation", and repeating it here would be the third heading in a
          row saying the same thing. What is worth saying is who wrote it. */}
      <header className="mb-3 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          {explanation.headline && (
            <p className="text-sm font-medium leading-6 text-fg">{explanation.headline}</p>
          )}
          <p className="mt-0.5 text-2xs text-fg-subtle">{generated}</p>
        </div>
        <Badge severity="neutral" title={explanation.label}>
          commentary only
        </Badge>
      </header>

      {explanation.sections ? (
        <div className="flex flex-col divide-y divide-line/60 border-y border-line/60">
          {SECTION_ORDER.map(([key, heading], index) => (
            <Detail
              key={key}
              heading={heading}
              body={explanation.sections![key]}
              defaultOpen={index === 0}
            />
          ))}
        </div>
      ) : (
        <p className="text-xs leading-5 text-fg-muted">{explanation.body}</p>
      )}

      <p className="mt-3 text-2xs leading-4 text-fg-subtle">{AUTHORITY_NOTE}</p>
    </Panel>
  );
}

function Detail({
  heading,
  body,
  defaultOpen,
}: {
  heading: string;
  body: string;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const Chevron = open ? IconChevronDown : IconChevronRight;

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 py-2 text-left transition-colors hover:text-fg"
      >
        <Chevron className="size-3 shrink-0 text-fg-subtle" />
        <span
          className={cn(
            "min-w-0 flex-1 truncate text-xs font-medium",
            open ? "text-fg" : "text-fg-muted",
          )}
        >
          {heading}
        </span>
      </button>
      {open && <p className="pb-2.5 pl-5 text-xs leading-5 text-fg-muted">{body}</p>}
    </div>
  );
}
