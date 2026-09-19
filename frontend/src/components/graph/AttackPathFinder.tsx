"use client";

import { useId, useState } from "react";

import { Button } from "@/components/ui/Button";
import { IconSearch } from "@/components/ui/icons";
import { ErrorState } from "@/components/ui/States";
import { cn } from "@/lib/cn";
import { getAttackPaths, getReplayAttackPaths } from "@/lib/api/client";
import type { InsightsMode } from "@/lib/security/useSecurityInsights";

/**
 * "Can an attacker sitting on A reach B, and how?" — the question the
 * `/analysis/attack-paths` endpoint answers. It had no UI at all before this;
 * the endpoint was reachable only by hand-crafting a URL.
 */
export function AttackPathFinder({
  experimentId,
  nodeIds,
  mode = "live",
  source,
  target,
  onSourceChange,
  onTargetChange,
  onSelectPath,
  selectedPath,
}: {
  experimentId: string;
  nodeIds: readonly string[];
  mode?: InsightsMode;
  source: string;
  target: string;
  onSourceChange: (value: string) => void;
  onTargetChange: (value: string) => void;
  onSelectPath: (path: readonly string[] | null) => void;
  selectedPath: readonly string[] | null;
}) {
  const listId = useId();
  const [paths, setPaths] = useState<string[][] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const search = () => {
    if (!source.trim() || !target.trim()) return;
    setLoading(true);
    setError(null);
    const request =
      mode === "live"
        ? getAttackPaths(experimentId, source.trim(), target.trim())
        : getReplayAttackPaths(experimentId, source.trim(), target.trim());
    request
      .then((response) => {
        setPaths(response.paths);
        onSelectPath(response.paths[0] ?? null);
      })
      .catch((err) => {
        setPaths(null);
        onSelectPath(null);
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoading(false));
  };

  const inputClass =
    "h-7 w-full rounded-md border border-line bg-raised px-2 font-mono text-2xs text-fg " +
    "placeholder:text-fg-subtle hover:border-line-strong focus:border-accent focus:outline-none";

  return (
    <div className="flex flex-col gap-2">
      <datalist id={listId}>
        {nodeIds.map((id) => (
          <option key={id} value={id} />
        ))}
      </datalist>

      <div className="flex items-end gap-1.5">
        <label className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="eyebrow">From</span>
          <input
            className={inputClass}
            list={listId}
            placeholder="agent-000"
            value={source}
            onChange={(e) => onSourceChange(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
          />
        </label>
        <label className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="eyebrow">To</span>
          <input
            className={inputClass}
            list={listId}
            placeholder="credential-000"
            value={target}
            onChange={(e) => onTargetChange(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
          />
        </label>
        <Button size="sm" onClick={search} disabled={loading || !source || !target}>
          <IconSearch className="size-3.5" />
        </Button>
      </div>

      {error && <ErrorState title="Path query failed" detail={error} />}

      {paths !== null && !error && (
        <div>
          {paths.length === 0 ? (
            <p className="text-2xs text-fg-subtle">
              No propagation-capable path of 6 hops or fewer exists between those two nodes.
            </p>
          ) : (
            <>
              <p className="mb-1.5 text-2xs text-fg-subtle">
                {paths.length} simple path{paths.length === 1 ? "" : "s"} of 6 hops or fewer
                (capped at 10). Select one to trace it on the graph.
              </p>
              <ul className="flex max-h-44 flex-col gap-1 overflow-y-auto">
                {paths.map((path, index) => {
                  const active = selectedPath?.join(">") === path.join(">");
                  return (
                    <li key={index}>
                      <button
                        type="button"
                        onClick={() => onSelectPath(active ? null : path)}
                        className={cn(
                          "w-full rounded-sm border px-2 py-1 text-left transition-colors",
                          active
                            ? "border-accent-line bg-accent-soft"
                            : "border-line bg-raised hover:border-line-strong",
                        )}
                      >
                        <span className="flex items-baseline justify-between gap-2">
                          <span className="truncate font-mono text-2xs text-fg-muted">
                            {path.join(" → ")}
                          </span>
                          <span className="shrink-0 text-2xs text-fg-subtle">
                            {path.length - 1} hop{path.length === 2 ? "" : "s"}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
