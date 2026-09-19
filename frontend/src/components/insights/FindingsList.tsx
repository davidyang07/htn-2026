"use client";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { IconShieldCheck, IconWrench } from "@/components/ui/icons";
import { EmptyState } from "@/components/ui/States";
import type { ExperimentConfig, RemediationResponse } from "@/lib/api/client";
import { configLabel } from "@/lib/vocabulary";

type Recommendation = RemediationResponse["recommendations"][number];

/**
 * Remediation findings. Each carries the exact `ExperimentConfig` change that
 * would apply it, shown as a before → after diff rather than raw JSON, plus
 * the action that actually re-tests it.
 */
export function FindingsList({
  recommendations,
  baseConfig,
  onValidate,
  validatingKey,
  disabled,
}: {
  recommendations: readonly Recommendation[];
  baseConfig: ExperimentConfig | null;
  onValidate?: (configDiff: Record<string, unknown>) => void;
  /** JSON key of the diff currently being validated, if any. */
  validatingKey?: string | null;
  disabled?: boolean;
}) {
  if (recommendations.length === 0) {
    return (
      <EmptyState
        icon={<IconShieldCheck className="size-5" />}
        title="No remediation findings"
        description="The engine found no configuration change it could causally justify for this run. That is a clean result, not a missing one — findings appear when compromise or a security-plane gap crosses its threshold."
      />
    );
  }

  return (
    <ul className="flex flex-col gap-2.5">
      {recommendations.map((recommendation, index) => {
        const diff = recommendation.config_diff as Record<string, unknown>;
        const diffKey = JSON.stringify(diff);
        const busy = validatingKey === diffKey;
        return (
          <li
            key={index}
            className="rounded-md border border-line bg-raised p-3.5 transition-colors hover:border-line-strong"
          >
            <div className="mb-2 flex items-start gap-2.5">
              <span className="mt-0.5 shrink-0 rounded-sm bg-warn-soft p-1 text-warn">
                <IconWrench className="size-3.5" />
              </span>
              <p className="min-w-0 flex-1 text-sm leading-6 text-fg">
                {recommendation.description}
              </p>
            </div>

            <div className="ml-8 flex flex-col gap-1.5">
              <p className="eyebrow">Proposed change</p>
              <ul className="flex flex-col gap-1">
                {Object.entries(diff).map(([key, value]) => {
                  const current = baseConfig
                    ? (baseConfig as unknown as Record<string, unknown>)[key]
                    : undefined;
                  return (
                    <li key={key} className="flex flex-wrap items-baseline gap-2 text-xs">
                      <span className="text-fg-muted">{configLabel(key)}</span>
                      <span className="font-mono text-2xs text-fg-subtle">{key}</span>
                      {current !== undefined && (
                        <>
                          <span className="font-mono text-2xs text-fg-subtle line-through">
                            {JSON.stringify(current)}
                          </span>
                          <span aria-hidden className="text-fg-subtle">
                            →
                          </span>
                        </>
                      )}
                      <Badge severity="ok" className="font-mono">
                        {JSON.stringify(value)}
                      </Badge>
                    </li>
                  );
                })}
              </ul>
            </div>

            {onValidate && (
              <div className="ml-8 mt-3 flex items-center gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  disabled={disabled || busy || !baseConfig}
                  onClick={() => onValidate(diff)}
                >
                  {busy ? "Re-testing…" : "Validate fix"}
                </Button>
                <span className="text-2xs text-fg-subtle">
                  Runs the current config and the patched config to completion, then compares them.
                </span>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
