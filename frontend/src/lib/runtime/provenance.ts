// Which model actually answered, and who actually served it.
//
// Derived from MODEL_REQUESTED events and nothing else, because those events
// are emitted only when a real call was made (app/runtime/session.py
// `record_model_call`). A worker that ran as a deterministic stand-in emits
// none, and therefore gets no provenance here — which is the difference
// between evidence and decoration.
//
// The displayed provider name comes from the *endpoint host that was called*,
// not from the `provider` metadata field. That field records the wire protocol
// the client spoke ("OpenAI"), so rendering it verbatim would credit a vendor
// that never served the request. The host cannot lie about who was called.

import type { Event } from "@/lib/stream/reducer";

export type ModelProvenance = {
  /** e.g. "z-ai/glm-5.3" */
  model: string;
  /** Display name of whoever actually served it, e.g. "OpenRouter". */
  provider: string;
  /** The host as recorded, e.g. "openrouter.ai". Never prettified. */
  endpointHost: string;
  /** "sponsor" | "sponsor_fallback" | "runpod" | … — verbatim from the event. */
  route: string;
  fallbackUsed: boolean;
  calls: number;
  /** Sum of the per-call latencies this worker reported. */
  latencyMs: number;
};

/** Known hosts get their product name; everything else keeps its hostname. */
const HOST_LABEL: ReadonlyArray<[RegExp, string]> = [
  [/(^|\.)openrouter\.ai$/i, "OpenRouter"],
  [/(^|\.)runpod\.(ai|io)$/i, "RunPod"],
  [/(^|\.)api\.openai\.com$/i, "OpenAI"],
  [/(^|\.)anthropic\.com$/i, "Anthropic"],
];

export function providerLabel(endpointHost: string): string {
  for (const [pattern, label] of HOST_LABEL) {
    if (pattern.test(endpointHost)) return label;
  }
  return endpointHost;
}

/** "sponsor_fallback" → "sponsor fallback". Routes are shown, never invented. */
export function routeLabel(route: string): string {
  return route.replace(/_/g, " ");
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** A worker that did not take the planned route, and the route it took. */
export type FallbackRoute = { workerId: string; route: string };

export type ProvenanceIndex = {
  /** Provenance per worker id, for workers that made at least one real call. */
  byWorker: ReadonlyMap<string, ModelProvenance>;
  /** Every worker whose call reported `fallback_used`, with the route taken. */
  fallbacks: readonly FallbackRoute[];
  /** Distinct model+host combinations seen, most-used first. */
  distinct: readonly ModelProvenance[];
  /** The model behind the most calls, or null when nothing real ran. */
  primary: ModelProvenance | null;
  /** Total real model calls recorded in this session. */
  calls: number;
};

export const EMPTY_PROVENANCE: ProvenanceIndex = {
  byWorker: new Map(),
  fallbacks: [],
  distinct: [],
  primary: null,
  calls: 0,
};

export function deriveProvenance(events: readonly Event[]): ProvenanceIndex {
  const byWorker = new Map<string, ModelProvenance>();
  const distinct = new Map<string, ModelProvenance>();
  let calls = 0;

  for (const event of events) {
    // MODEL_RESPONDED carries the same payload; counting both would double
    // every call. The request is the one that always exists.
    if (event.event_type !== "MODEL_REQUESTED") continue;
    const meta = (event.metadata ?? {}) as Record<string, unknown>;
    const model = str(meta["model"]);
    const endpointHost = str(meta["endpoint_host"]);
    if (!model && !endpointHost) continue;

    calls += 1;
    const latency = num(meta["latency_ms"]);
    const route = str(meta["provider_route"]);
    const fallbackUsed = meta["fallback_used"] === true;
    const entry: ModelProvenance = {
      model,
      provider: providerLabel(endpointHost),
      endpointHost,
      route,
      fallbackUsed,
      calls: 1,
      latencyMs: latency,
    };

    const workerId = event.agent_id;
    if (workerId) {
      const prev = byWorker.get(workerId);
      byWorker.set(
        workerId,
        prev
          ? {
              // The latest call wins on identity — a worker that fell back to
              // a different route should read as the route it ended on.
              ...entry,
              calls: prev.calls + 1,
              latencyMs: prev.latencyMs + latency,
              fallbackUsed: prev.fallbackUsed || fallbackUsed,
            }
          : entry,
      );
    }

    const key = `${model}@${endpointHost}`;
    const seen = distinct.get(key);
    distinct.set(
      key,
      seen
        ? {
            ...seen,
            calls: seen.calls + 1,
            latencyMs: seen.latencyMs + latency,
            fallbackUsed: seen.fallbackUsed || fallbackUsed,
          }
        : { ...entry },
    );
  }

  const ranked = [...distinct.values()].sort((a, b) => b.calls - a.calls);
  // Reported per worker rather than rolled into the headline model: a fallback
  // is a fact about one worker's call, and attributing it to the session's
  // busiest model would name a route that model never took.
  const fallbacks: FallbackRoute[] = [...byWorker.entries()]
    .filter(([, p]) => p.fallbackUsed)
    .map(([workerId, p]) => ({ workerId, route: p.route }));

  return { byWorker, fallbacks, distinct: ranked, primary: ranked[0] ?? null, calls };
}
