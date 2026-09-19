import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createExperiment,
  fetchEventHistory,
  fetchIncidents,
  fetchReplaySnapshot,
  getAttackPaths,
  getBlastRadius,
  getCriticalNodes,
  getExperiment,
  getExperimentDetail,
  getMetrics,
  getProvenance,
  getRemediation,
  getReplayAttackPaths,
  getReplayBlastRadius,
  getReplayCriticalNodes,
  getReplayMetrics,
  getReplayProvenance,
  getReplayRemediation,
  getReplaySecurityGraph,
  getSecurityGraph,
  listExperiments,
  pauseExperiment,
  resumeExperiment,
  setSpeed,
  stopExperiment,
  type ExperimentConfig,
} from "./client";

const CONFIG: ExperimentConfig = {
  seed: 42,
  node_count: 60,
  edge_density: 2,
  software_type_count: 3,
  p_same: 0.15,
  p_cross: 0.03,
  max_ticks: 200,
  detector_sensitivity: 0.2,
  defense_enabled: true,
  initial_compromised: "highest_degree",
  real_agent_count: 0,
  model_provider: "mock",
  model_name: "qwen-mock",
  model_max_tokens: 64,
  model_timeout_s: 20,
  model_max_retries: 1,
  model_max_concurrency: 4,
  model_max_requests_per_experiment: 500,
  tool_count: 0,
  credential_count: 0,
  resource_count: 0,
  sentinel_count: 0,
  adaptive_detection_threshold: 0.3,
  false_quarantine_rate: 0,
  sentinel_compromise_rate: 0,
  attestation_replay_rate: 0,
  byzantine_collusion_rate: 0,
};

function okResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body } as Response;
}

function errResponse(status: number) {
  return { ok: false, status, json: async () => ({}) } as Response;
}

describe("api client", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("createExperiment POSTs the config to /api/experiments", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ experiment_id: "a", status: "running" }));
    const summary = await createExperiment(CONFIG);
    expect(summary.experiment_id).toBe("a");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/experiments$/);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual(CONFIG);
  });

  it("createExperiment throws on non-ok response", async () => {
    fetchMock.mockResolvedValueOnce(errResponse(422));
    await expect(createExperiment(CONFIG)).rejects.toThrow("422");
  });

  it("getExperiment GETs /api/experiments/{id}", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ experiment_id: "a", status: "finished" }));
    const summary = await getExperiment("a");
    expect(summary.status).toBe("finished");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/experiments\/a$/);
  });

  it("getExperiment throws on 404", async () => {
    fetchMock.mockResolvedValueOnce(errResponse(404));
    await expect(getExperiment("missing")).rejects.toThrow("404");
  });

  it.each([
    ["stopExperiment", stopExperiment, "stop"],
    ["pauseExperiment", pauseExperiment, "pause"],
    ["resumeExperiment", resumeExperiment, "resume"],
  ] as const)("%s POSTs /api/experiments/{id}/%s", async (_name, fn, action) => {
    fetchMock.mockResolvedValueOnce(okResponse({ experiment_id: "a", status: "running" }));
    await fn("a");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(new RegExp(`/api/experiments/a/${action}$`));
    expect(init?.method).toBe("POST");
  });

  it("setSpeed POSTs the multiplier as JSON", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ experiment_id: "a", status: "running" }));
    await setSpeed("a", 4);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/experiments\/a\/speed$/);
    expect(JSON.parse(init?.body as string)).toEqual({ multiplier: 4 });
  });

  it("setSpeed throws on 422 (out-of-range multiplier)", async () => {
    fetchMock.mockResolvedValueOnce(errResponse(422));
    await expect(setSpeed("a", 100)).rejects.toThrow("422");
  });

  it("Start and Reset would POST the identical canonical config object", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ experiment_id: "a", status: "running" }));
    await createExperiment(CONFIG);
    fetchMock.mockResolvedValueOnce(okResponse({ experiment_id: "b", status: "running" }));
    await createExperiment(CONFIG);

    const firstBody = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    const secondBody = JSON.parse(fetchMock.mock.calls[1][1]?.body as string);
    expect(firstBody).toEqual(secondBody);
  });

  it("listExperiments GETs /api/experiments with filters/cursor as query params", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ items: [], next_cursor: null }));
    await listExperiments({ status: "finished", defenseEnabled: true, limit: 10, cursor: "abc" });
    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe("/api/experiments");
    expect(parsed.searchParams.get("status")).toBe("finished");
    expect(parsed.searchParams.get("defense_enabled")).toBe("true");
    expect(parsed.searchParams.get("limit")).toBe("10");
    expect(parsed.searchParams.get("cursor")).toBe("abc");
  });

  it("listExperiments throws on non-ok response", async () => {
    fetchMock.mockResolvedValueOnce(errResponse(503));
    await expect(listExperiments()).rejects.toThrow("503");
  });

  it("getExperimentDetail GETs /api/experiments/{id}/detail", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ experiment_id: "a", is_complete: true }));
    const detail = await getExperimentDetail("a");
    expect(detail.is_complete).toBe(true);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/experiments\/a\/detail$/);
  });

  it("getExperimentDetail throws on 404", async () => {
    fetchMock.mockResolvedValueOnce(errResponse(404));
    await expect(getExperimentDetail("missing")).rejects.toThrow("404");
  });

  it("fetchEventHistory GETs /api/experiments/{id}/events with since_seq and limit", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ events: [], next_seq: null }));
    await fetchEventHistory("a", 5, 200);
    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe("/api/experiments/a/events");
    expect(parsed.searchParams.get("since_seq")).toBe("5");
    expect(parsed.searchParams.get("limit")).toBe("200");
  });

  it("fetchIncidents GETs /api/experiments/{id}/incidents with since_seq", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ events: [], next_seq: null }));
    await fetchIncidents("a", -1);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/experiments\/a\/incidents\?since_seq=-1$/);
  });

  it("fetchReplaySnapshot GETs /api/experiments/{id}/replay-snapshot", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ type: "snapshot", last_seq: 60 }));
    const snapshot = await fetchReplaySnapshot("a");
    expect(snapshot.last_seq).toBe(60);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/experiments\/a\/replay-snapshot$/);
  });

  it("fetchReplaySnapshot throws on 404 (no tick-0 events persisted)", async () => {
    fetchMock.mockResolvedValueOnce(errResponse(404));
    await expect(fetchReplaySnapshot("missing")).rejects.toThrow("404");
  });

  it("getSecurityGraph GETs /api/experiments/{id}/graph", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ nodes: [], edges: [] }));
    await getSecurityGraph("a");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/experiments\/a\/graph$/);
  });

  it("getAttackPaths GETs .../analysis/attack-paths with source/target params", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ paths: [] }));
    await getAttackPaths("a", "agent-000", "agent-001");
    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe("/api/experiments/a/analysis/attack-paths");
    expect(parsed.searchParams.get("source")).toBe("agent-000");
    expect(parsed.searchParams.get("target")).toBe("agent-001");
  });

  it("getBlastRadius GETs .../analysis/blast-radius", async () => {
    fetchMock.mockResolvedValueOnce(
      okResponse({ compromised: [], reachable: [], fraction: 0 }),
    );
    await getBlastRadius("a");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/experiments\/a\/analysis\/blast-radius$/);
  });

  it("getCriticalNodes GETs .../analysis/critical-nodes with an optional top_n param", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ nodes: [] }));
    await getCriticalNodes("a", 3);
    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe("/api/experiments/a/analysis/critical-nodes");
    expect(parsed.searchParams.get("top_n")).toBe("3");
  });

  it("getProvenance GETs .../analysis/provenance with a node_id param", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ chain: ["agent-000"] }));
    await getProvenance("a", "agent-000");
    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe("/api/experiments/a/analysis/provenance");
    expect(parsed.searchParams.get("node_id")).toBe("agent-000");
  });

  it("getMetrics GETs .../metrics", async () => {
    fetchMock.mockResolvedValueOnce(
      okResponse({
        compromise_fraction: 0,
        retained_utility: 1,
        blast_radius_fraction: 0,
        privileged_exposure: 0,
        security_plane_integrity: 1,
        attack_success_rate: 0,
        false_quarantine_rate: 0,
  sentinel_compromise_rate: 0,
  attestation_replay_rate: 0,
  byzantine_collusion_rate: 0,
      }),
    );
    await getMetrics("a");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/experiments\/a\/metrics$/);
  });

  it("getRemediation GETs .../remediation", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ recommendations: [] }));
    await getRemediation("a");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/experiments\/a\/remediation$/);
  });

  it("getSecurityGraph throws on non-ok response", async () => {
    fetchMock.mockResolvedValueOnce(errResponse(404));
    await expect(getSecurityGraph("missing")).rejects.toThrow("404");
  });

  it("getReplaySecurityGraph GETs /api/experiments/{id}/replay/graph", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ nodes: [], edges: [] }));
    await getReplaySecurityGraph("a");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/experiments\/a\/replay\/graph$/);
  });

  it("getReplayAttackPaths GETs .../replay/analysis/attack-paths with source/target params", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ paths: [] }));
    await getReplayAttackPaths("a", "n1", "n2");
    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe("/api/experiments/a/replay/analysis/attack-paths");
    expect(parsed.searchParams.get("source")).toBe("n1");
    expect(parsed.searchParams.get("target")).toBe("n2");
  });

  it("getReplayBlastRadius GETs .../replay/analysis/blast-radius", async () => {
    fetchMock.mockResolvedValueOnce(
      okResponse({ compromised: [], reachable: [], fraction: 0 }),
    );
    await getReplayBlastRadius("a");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/experiments\/a\/replay\/analysis\/blast-radius$/);
  });

  it("getReplayCriticalNodes GETs .../replay/analysis/critical-nodes with an optional top_n param", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ nodes: [] }));
    await getReplayCriticalNodes("a", 3);
    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe("/api/experiments/a/replay/analysis/critical-nodes");
    expect(parsed.searchParams.get("top_n")).toBe("3");
  });

  it("getReplayProvenance GETs .../replay/analysis/provenance with a node_id param", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ chain: ["agent-000"] }));
    await getReplayProvenance("a", "agent-000");
    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe("/api/experiments/a/replay/analysis/provenance");
    expect(parsed.searchParams.get("node_id")).toBe("agent-000");
  });

  it("getReplayMetrics GETs .../replay/metrics", async () => {
    fetchMock.mockResolvedValueOnce(
      okResponse({
        compromise_fraction: 0,
        retained_utility: 1,
        blast_radius_fraction: 0,
        privileged_exposure: 0,
        security_plane_integrity: 1,
        attack_success_rate: 0,
        false_quarantine_rate: 0,
        detection_latency: null,
        containment_latency: null,
      }),
    );
    await getReplayMetrics("a");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/experiments\/a\/replay\/metrics$/);
  });

  it("getReplayRemediation GETs .../replay/remediation", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ recommendations: [] }));
    await getReplayRemediation("a");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/experiments\/a\/replay\/remediation$/);
  });
});
