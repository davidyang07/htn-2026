import { describe, expect, it } from "vitest";

import type { Event } from "@/lib/stream/reducer";

import { deriveProvenance, providerLabel, routeLabel } from "./provenance";

const SESSION = "44444444-4444-4444-4444-444444444444";

let nextSeq = 0;

function event(event_type: string, overrides: Partial<Event> = {}): Event {
  return {
    event_id: `event-${nextSeq}`,
    seq: nextSeq++,
    schema_version: 1,
    experiment_id: SESSION,
    wall_time: "2026-03-02T00:00:00Z",
    sim_tick: nextSeq,
    event_type: event_type as Event["event_type"],
    metadata: {},
    ...overrides,
  };
}

function modelCall(agentId: string, overrides: Record<string, unknown> = {}): Event[] {
  const metadata = {
    provider: "OpenAI",
    model: "z-ai/glm-5.3",
    endpoint_host: "openrouter.ai",
    provider_route: "sponsor",
    fallback_used: false,
    latency_ms: 1000,
    ...overrides,
  };
  return [
    event("MODEL_REQUESTED", { agent_id: agentId, metadata }),
    event("MODEL_RESPONDED", { agent_id: agentId, metadata }),
  ];
}

describe("providerLabel", () => {
  it("names the host that was actually called", () => {
    expect(providerLabel("openrouter.ai")).toBe("OpenRouter");
    expect(providerLabel("api.runpod.ai")).toBe("RunPod");
    expect(providerLabel("api.openai.com")).toBe("OpenAI");
  });

  it("keeps an unknown host verbatim rather than guessing a vendor", () => {
    expect(providerLabel("inference.internal")).toBe("inference.internal");
    expect(providerLabel("")).toBe("");
  });
});

describe("routeLabel", () => {
  it("reads the recorded route without renaming it", () => {
    expect(routeLabel("sponsor_fallback")).toBe("sponsor fallback");
  });
});

describe("deriveProvenance", () => {
  it("is empty when nothing real ran", () => {
    nextSeq = 0;
    const result = deriveProvenance([
      event("AGENT_CREATED", { agent_id: "developer" }),
      event("TASK_COMPLETED", { agent_id: "developer" }),
    ]);
    expect(result.calls).toBe(0);
    expect(result.primary).toBeNull();
    expect(result.byWorker.size).toBe(0);
  });

  it("counts each call once, not once per request/response pair", () => {
    nextSeq = 0;
    const result = deriveProvenance([
      ...modelCall("developer"),
      ...modelCall("reviewer"),
    ]);
    expect(result.calls).toBe(2);
    expect(result.byWorker.get("developer")?.calls).toBe(1);
  });

  it("credits the endpoint host, never the wire-protocol vendor field", () => {
    nextSeq = 0;
    const result = deriveProvenance(modelCall("developer"));
    expect(result.primary?.provider).toBe("OpenRouter");
    expect(result.primary?.model).toBe("z-ai/glm-5.3");
    expect(result.primary?.endpointHost).toBe("openrouter.ai");
  });

  it("accumulates a worker's calls and latency", () => {
    nextSeq = 0;
    const result = deriveProvenance([
      ...modelCall("developer", { latency_ms: 1000 }),
      ...modelCall("developer", { latency_ms: 500 }),
    ]);
    const developer = result.byWorker.get("developer");
    expect(developer?.calls).toBe(2);
    expect(developer?.latencyMs).toBe(1500);
  });

  it("reports a fallback route once any call took it", () => {
    nextSeq = 0;
    const result = deriveProvenance([
      ...modelCall("developer", { provider_route: "sponsor" }),
      ...modelCall("replacement-researcher", {
        provider_route: "sponsor_fallback",
        fallback_used: true,
      }),
    ]);
    expect(result.byWorker.get("developer")?.fallbackUsed).toBe(false);
    const replacement = result.byWorker.get("replacement-researcher");
    expect(replacement?.fallbackUsed).toBe(true);
    expect(replacement?.route).toBe("sponsor_fallback");
  });

  it("ranks distinct models by how much work each actually did", () => {
    nextSeq = 0;
    const result = deriveProvenance([
      ...modelCall("developer", { model: "a", endpoint_host: "openrouter.ai" }),
      ...modelCall("reviewer", { model: "b", endpoint_host: "api.runpod.ai" }),
      ...modelCall("repo-analyst", { model: "b", endpoint_host: "api.runpod.ai" }),
    ]);
    expect(result.distinct.map((p) => p.model)).toEqual(["b", "a"]);
    expect(result.primary?.provider).toBe("RunPod");
  });
});

describe("fallback attribution", () => {
  it("names the worker that fell back, not the session's busiest model", () => {
    nextSeq = 0;
    const result = deriveProvenance([
      ...modelCall("developer"),
      ...modelCall("reviewer"),
      ...modelCall("replacement-researcher", {
        provider_route: "sponsor_fallback",
        fallback_used: true,
      }),
    ]);
    expect(result.fallbacks).toEqual([
      { workerId: "replacement-researcher", route: "sponsor_fallback" },
    ]);
    // The headline model never took that route and must not be credited with it.
    expect(result.primary?.fallbackUsed).toBe(true);
    expect(result.byWorker.get("developer")?.fallbackUsed).toBe(false);
  });

  it("has no fallbacks when every call took the planned route", () => {
    nextSeq = 0;
    expect(deriveProvenance(modelCall("developer")).fallbacks).toEqual([]);
  });
});
