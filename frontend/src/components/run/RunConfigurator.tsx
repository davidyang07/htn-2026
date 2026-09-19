"use client";

import { useState } from "react";

import { Panel, PanelDivider } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { ChipMultiSelect, NumberField, SelectField, ToggleField } from "@/components/ui/Field";
import { IconSpark } from "@/components/ui/icons";
import { WarningBanner } from "@/components/ui/States";
import type { ExperimentConfig } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { BOUNDS, clamp, DEFAULT_CONFIG, PRESETS } from "@/lib/experiment/presets";
import { SCENARIOS, scenarioMeta } from "@/lib/vocabulary";

type Field = keyof ExperimentConfig;

/**
 * The launch surface: everything that defines *what system is being tested*
 * and *what is being thrown at it*, grouped by that question rather than by
 * the order the fields happen to appear in the Pydantic model.
 *
 * Every field is an `ExperimentConfig` key sent verbatim to
 * `POST /api/experiments` — the machine name is shown under each label so a
 * run is reproducible from the UI alone.
 */
export function RunConfigurator({
  disabled,
  onStart,
  initialConfig = DEFAULT_CONFIG,
  submitLabel = "Launch assessment",
}: {
  disabled: boolean;
  onStart: (config: ExperimentConfig) => void;
  initialConfig?: ExperimentConfig;
  submitLabel?: string;
}) {
  const [draft, setDraft] = useState<ExperimentConfig>(initialConfig);
  const [presetId, setPresetId] = useState<string | null>("baseline");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const set = <K extends Field>(key: K, value: ExperimentConfig[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    setPresetId(null);
  };

  const setNumber = (key: Field & keyof typeof BOUNDS, value: number, integer = true) => {
    const [min, max] = BOUNDS[key];
    set(key, clamp(integer ? Math.trunc(value) : value, min, max) as never);
  };

  const toggleScenario = (scenario: string) => {
    setPresetId(null);
    setDraft((prev) => {
      const current = prev.active_scenarios ?? [];
      if (current.includes(scenario)) {
        return { ...prev, active_scenarios: current.filter((s) => s !== scenario) };
      }
      // Scenarios that own the tick increment are mutually exclusive
      // (docs/PLAN.md §4) — selecting one deselects its counterpart rather
      // than letting the backend silently double-tick.
      const exclusive = scenarioMeta(scenario).exclusiveWith ?? [];
      const kept = current.filter((s) => !exclusive.includes(s));
      return { ...prev, active_scenarios: [...kept, scenario] };
    });
  };

  const scenarios = draft.active_scenarios ?? [];
  const usesAdaptive = scenarios.includes("adaptive_attacker");
  const usesPromptInjection = scenarios.includes("prompt_injection");
  const usesSentinelCompromise = scenarios.includes("sentinel_compromise");
  const usesAttestation = scenarios.includes("attestation");
  const usesCollusion = scenarios.includes("byzantine_collusion");
  const needsSentinels =
    (usesSentinelCompromise || usesAttestation) && draft.sentinel_count === 0;
  const needsCredentials = usesCollusion && draft.credential_count === 0;
  const needsRealAgents = usesPromptInjection && draft.real_agent_count === 0;

  return (
    <Panel>
      <form
        className="flex flex-col"
        onSubmit={(e) => {
          e.preventDefault();
          onStart(draft);
        }}
      >
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <span className="eyebrow mr-1">Preset</span>
          {PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              title={preset.description}
              disabled={disabled}
              onClick={() => {
                setDraft(preset.config);
                setPresetId(preset.id);
              }}
              className={cn(
                "rounded-md border px-2 py-1 text-xs font-medium transition-colors duration-100",
                "disabled:cursor-not-allowed disabled:opacity-40",
                presetId === preset.id
                  ? "border-accent-line bg-accent-soft text-accent"
                  : "border-line bg-raised text-fg-muted hover:border-line-strong hover:text-fg",
              )}
            >
              {preset.label}
            </button>
          ))}
        </div>
        {presetId && (
          <p className="-mt-2 mb-4 flex items-start gap-2 text-xs leading-5 text-fg-subtle">
            <IconSpark className="mt-0.5 size-3.5 shrink-0 text-fg-subtle" />
            {PRESETS.find((p) => p.id === presetId)?.description}
          </p>
        )}

        <PanelDivider label="System under test" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
          <NumberField
            label="Agents"
            hint="node_count · 25–100"
            value={draft.node_count}
            disabled={disabled}
            onChange={(v) => setNumber("node_count", v)}
          />
          <NumberField
            label="Edge density"
            hint="edge_density · 1–5"
            value={draft.edge_density}
            disabled={disabled}
            onChange={(v) => setNumber("edge_density", v)}
          />
          <NumberField
            label="Software diversity"
            hint="software_type_count · 1–5"
            value={draft.software_type_count}
            disabled={disabled}
            onChange={(v) => setNumber("software_type_count", v)}
          />
          <SelectField
            label="Initial foothold"
            hint="initial_compromised"
            value={draft.initial_compromised}
            disabled={disabled}
            onChange={(v) => set("initial_compromised", v)}
            options={[
              { value: "highest_degree", label: "Highest-degree agent" },
              { value: "random_node", label: "Random agent" },
            ]}
          />
          <NumberField
            label="Seed"
            hint="seed · determinism key"
            value={draft.seed}
            disabled={disabled}
            onChange={(v) => set("seed", Math.trunc(v))}
          />
        </div>

        <PanelDivider label="Attack surface" />
        <p className="-mt-1 mb-3 text-xs leading-5 text-fg-subtle">
          Typed non-agent nodes the security graph is built from. Leave at zero for a pure
          agent-mesh test; add them to model tool access, credential blast radius and a security
          plane the attacker can turn against you.
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <NumberField
            label="Tools"
            hint="tool_count · 0–20"
            value={draft.tool_count}
            disabled={disabled}
            onChange={(v) => setNumber("tool_count", v)}
          />
          <NumberField
            label="Credentials"
            hint="credential_count · 0–20"
            value={draft.credential_count}
            disabled={disabled}
            onChange={(v) => setNumber("credential_count", v)}
          />
          <NumberField
            label="Resources"
            hint="resource_count · 0–20"
            value={draft.resource_count}
            disabled={disabled}
            onChange={(v) => setNumber("resource_count", v)}
          />
          <NumberField
            label="Sentinels"
            hint="sentinel_count · 0–5"
            value={draft.sentinel_count}
            disabled={disabled}
            onChange={(v) => setNumber("sentinel_count", v)}
          />
        </div>

        <PanelDivider label="Attack scenarios" />
        <ChipMultiSelect
          ariaLabel="Active attack scenarios"
          disabled={disabled}
          options={SCENARIOS.map((s) => ({ value: s.value, label: s.label, hint: s.hint }))}
          selected={scenarios}
          onToggle={toggleScenario}
        />
        <ul className="mt-2.5 flex flex-col gap-1">
          {scenarios.map((value) => (
            <li key={value} className="flex items-start gap-2 text-2xs leading-4 text-fg-subtle">
              <span aria-hidden className="mt-[5px] size-1 shrink-0 rounded-full bg-accent/70" />
              <span>
                <span className="font-medium text-fg-muted">{scenarioMeta(value).label}</span>{" "}
                — {scenarioMeta(value).hint}
              </span>
            </li>
          ))}
          {scenarios.length === 0 && (
            <li className="text-2xs text-warn">
              No scenario selected — the system will be built and observed, but never attacked.
            </li>
          )}
        </ul>

        {(usesAdaptive ||
          usesPromptInjection ||
          usesSentinelCompromise ||
          usesAttestation ||
          usesCollusion) && (
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
            {!usesAdaptive && (
              <>
                <NumberField
                  label="Same-stack rate"
                  hint="p_same · 0–1"
                  step={0.01}
                  value={draft.p_same}
                  disabled={disabled}
                  onChange={(v) => setNumber("p_same", v, false)}
                />
                <NumberField
                  label="Cross-stack rate"
                  hint="p_cross · 0–1"
                  step={0.01}
                  value={draft.p_cross}
                  disabled={disabled}
                  onChange={(v) => setNumber("p_cross", v, false)}
                />
              </>
            )}
            {usesAdaptive && (
              <NumberField
                label="Adaptive threshold"
                hint="adaptive_detection_threshold"
                step={0.05}
                value={draft.adaptive_detection_threshold}
                disabled={disabled}
                onChange={(v) => setNumber("adaptive_detection_threshold", v, false)}
              />
            )}
            {usesPromptInjection && (
              <>
                <NumberField
                  label="LLM-backed agents"
                  hint="real_agent_count · 0–20"
                  value={draft.real_agent_count}
                  disabled={disabled}
                  onChange={(v) => setNumber("real_agent_count", v)}
                />
                <SelectField
                  label="Model provider"
                  hint="model_provider"
                  value={draft.model_provider}
                  disabled={disabled || draft.real_agent_count === 0}
                  onChange={(v) => set("model_provider", v)}
                  options={[
                    { value: "mock", label: "Mock (deterministic)" },
                    { value: "vllm", label: "vLLM endpoint" },
                  ]}
                />
              </>
            )}
            {usesSentinelCompromise && (
              <NumberField
                label="Sentinel-subversion rate"
                hint="sentinel_compromise_rate"
                step={0.01}
                value={draft.sentinel_compromise_rate}
                disabled={disabled}
                onChange={(v) => setNumber("sentinel_compromise_rate", v, false)}
              />
            )}
            {usesAttestation && (
              <NumberField
                label="Attestation-replay rate"
                hint="attestation_replay_rate"
                step={0.01}
                value={draft.attestation_replay_rate}
                disabled={disabled}
                onChange={(v) => setNumber("attestation_replay_rate", v, false)}
              />
            )}
            {usesCollusion && (
              <NumberField
                label="Collusion rate"
                hint="byzantine_collusion_rate"
                step={0.01}
                value={draft.byzantine_collusion_rate}
                disabled={disabled}
                onChange={(v) => setNumber("byzantine_collusion_rate", v, false)}
              />
            )}
          </div>
        )}

        {(needsSentinels || needsCredentials || needsRealAgents) && (
          <WarningBanner className="mt-3">
            <ul className="flex flex-col gap-0.5">
              {needsSentinels && (
                <li>
                  Sentinel subversion and attestation replay need a security plane — set{" "}
                  <span className="font-mono">sentinel_count</span> above zero or the scenario will
                  no-op.
                </li>
              )}
              {needsCredentials && (
                <li>
                  Byzantine collusion targets a credential — set{" "}
                  <span className="font-mono">credential_count</span> above zero or the scenario
                  will no-op.
                </li>
              )}
              {needsRealAgents && (
                <li>
                  Indirect prompt injection needs LLM-backed agents — set{" "}
                  <span className="font-mono">real_agent_count</span> above zero or the scenario
                  will no-op.
                </li>
              )}
            </ul>
          </WarningBanner>
        )}

        {usesPromptInjection && draft.real_agent_count > 0 && draft.model_provider === "vllm" && (
          <WarningBanner className="mt-3">
            The vLLM provider requires <span className="font-mono">VLLM_BASE_URL</span> configured
            on the backend; without it the launch fails with a 400.
          </WarningBanner>
        )}

        <PanelDivider label="Defense posture" />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <ToggleField
            label="Anomaly detection & quarantine"
            hint="defense_enabled"
            checked={draft.defense_enabled}
            disabled={disabled}
            onChange={(v) => set("defense_enabled", v)}
          />
          <NumberField
            label="Detector sensitivity"
            hint="detector_sensitivity · 0–1"
            step={0.05}
            value={draft.detector_sensitivity}
            disabled={disabled || !draft.defense_enabled}
            onChange={(v) => setNumber("detector_sensitivity", v, false)}
          />
          <NumberField
            label="False-quarantine rate"
            hint="false_quarantine_rate · subverted authority"
            step={0.01}
            value={draft.false_quarantine_rate}
            disabled={disabled}
            onChange={(v) => setNumber("false_quarantine_rate", v, false)}
          />
        </div>

        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="mt-4 self-start text-xs font-medium text-fg-subtle transition-colors hover:text-fg-muted"
        >
          {showAdvanced ? "− Hide" : "+ Show"} run limits
        </button>
        {showAdvanced && (
          <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <NumberField
              label="Max ticks"
              hint="max_ticks · 1–2000"
              value={draft.max_ticks}
              disabled={disabled}
              onChange={(v) => setNumber("max_ticks", v)}
            />
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <p className="text-2xs leading-4 text-fg-subtle">
            Backend <span className="font-mono">Field(...)</span> bounds are the source of truth;
            these inputs mirror them for convenience and the backend re-validates every value.
          </p>
          <Button type="submit" variant="primary" disabled={disabled}>
            {submitLabel}
          </Button>
        </div>
      </form>
    </Panel>
  );
}
