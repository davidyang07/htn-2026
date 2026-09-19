import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ExperimentConfig, MetricsResponse } from "@/lib/api/client";
import type { StreamFrame } from "@/lib/stream/reducer";

import { runExperimentToCompletion } from "./runToCompletion";

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

const EXPERIMENT_ID = "exp-1";

const METRICS_RESPONSE: MetricsResponse = {
  compromise_fraction: 0.1,
  retained_utility: 0.8,
  blast_radius_fraction: 0.2,
  privileged_exposure: 1,
  security_plane_integrity: 1,
  attack_success_rate: 0.5,
  false_quarantine_rate: 0,
  detection_latency: 2,
  containment_latency: 1,
};

function okResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body } as Response;
}

function summary(status: "running" | "paused" | "finished" | "stopped", lastSeq = -1) {
  return { experiment_id: EXPERIMENT_ID, status, sim_tick: 0, last_seq: lastSeq, config: CONFIG };
}

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  push(frame: StreamFrame) {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }
}

const snapshotFrame: StreamFrame = {
  type: "snapshot",
  experiment_id: EXPERIMENT_ID,
  last_seq: -1,
  sim_tick: 0,
  status: "running",
  nodes: [
    { id: "a", software_type: "x", security_state: "healthy", agent_kind: "simulated" },
    { id: "b", software_type: "y", security_state: "healthy", agent_kind: "simulated" },
  ],
  edges: [{ source: "a", target: "b" }],
};

const compromiseFrame: StreamFrame = {
  type: "event",
  event: {
    sim_tick: 1,
    event_type: "COMPROMISE_SUCCEEDED",
    source_agent_id: "a",
    target_agent_id: "b",
    event_id: "11111111-1111-1111-1111-111111111111",
    seq: 0,
    schema_version: 1,
    experiment_id: EXPERIMENT_ID,
    wall_time: "2026-08-25T00:00:00Z",
  },
};

const otherEventFrame: StreamFrame = {
  type: "event",
  event: {
    sim_tick: 2,
    event_type: "ANOMALY_DETECTED",
    agent_id: "b",
    event_id: "22222222-2222-2222-2222-222222222222",
    seq: 1,
    schema_version: 1,
    experiment_id: EXPERIMENT_ID,
    wall_time: "2026-08-25T00:00:01Z",
  },
};

describe("runExperimentToCompletion", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  function callsMatching(method: string, pathSuffix: string) {
    return fetchMock.mock.calls.filter(([url, init]) => {
      const m = (init as RequestInit | undefined)?.method ?? "GET";
      return m === method && String(url).endsWith(pathSuffix);
    });
  }

  it("resolves with the rich MetricsResponse fetched over REST once status polling sees a terminal state", async () => {
    let getExperimentCalls = 0;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "POST" && String(url).endsWith("/api/experiments")) {
        return okResponse(summary("running"));
      }
      if (method === "GET" && String(url).endsWith(`/api/experiments/${EXPERIMENT_ID}/metrics`)) {
        return okResponse(METRICS_RESPONSE);
      }
      if (method === "GET" && String(url).endsWith(`/api/experiments/${EXPERIMENT_ID}`)) {
        getExperimentCalls += 1;
        return okResponse(
          getExperimentCalls === 1 ? summary("running") : summary("finished", 1),
        );
      }
      if (method === "POST" && String(url).endsWith(`/api/experiments/${EXPERIMENT_ID}/stop`)) {
        return okResponse(summary("stopped"));
      }
      throw new Error(`unexpected fetch call: ${method} ${url}`);
    });

    const resultPromise = runExperimentToCompletion(CONFIG);

    // Let createExperiment's microtask resolve and the WS get constructed.
    await vi.advanceTimersByTimeAsync(0);
    expect(FakeWebSocket.instances).toHaveLength(1);
    const ws = FakeWebSocket.instances[0];
    expect(ws.url).toContain(EXPERIMENT_ID);

    ws.push(snapshotFrame);
    ws.push(compromiseFrame);
    ws.push(otherEventFrame);

    // First poll: still running.
    await vi.advanceTimersByTimeAsync(1000);
    expect(callsMatching("GET", `/api/experiments/${EXPERIMENT_ID}`)).toHaveLength(1);

    // Second poll: finished -> resolves.
    await vi.advanceTimersByTimeAsync(1000);

    const result = await resultPromise;

    expect(result.experimentId).toBe(EXPERIMENT_ID);
    expect(result.metrics).toEqual(METRICS_RESPONSE);

    const stopCalls = callsMatching("POST", `/api/experiments/${EXPERIMENT_ID}/stop`);
    expect(stopCalls).toHaveLength(1);
    expect(ws.closed).toBe(true);
  });

  it("waits for locally-observed events to catch up to the terminal last_seq before finalizing metrics", async () => {
    // Regression: status polling can report "finished" before this WS
    // connection has actually received/applied the final tick's events
    // (they're independent connections) — sampling metrics right when
    // status flips would silently under-report a comparison arm's result.
    let getExperimentCalls = 0;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "POST" && String(url).endsWith("/api/experiments")) {
        return okResponse(summary("running"));
      }
      if (method === "GET" && String(url).endsWith(`/api/experiments/${EXPERIMENT_ID}/metrics`)) {
        return okResponse(METRICS_RESPONSE);
      }
      if (method === "GET" && String(url).endsWith(`/api/experiments/${EXPERIMENT_ID}`)) {
        getExperimentCalls += 1;
        // Backend reports "finished" with last_seq=1 (the otherEventFrame)
        // even though this WS hasn't delivered that far yet.
        return okResponse(getExperimentCalls === 1 ? summary("running") : summary("finished", 1));
      }
      if (method === "POST" && String(url).endsWith(`/api/experiments/${EXPERIMENT_ID}/stop`)) {
        return okResponse(summary("stopped"));
      }
      throw new Error(`unexpected fetch call: ${method} ${url}`);
    });

    const resultPromise = runExperimentToCompletion(CONFIG);

    await vi.advanceTimersByTimeAsync(0);
    const ws = FakeWebSocket.instances[0];

    // Only the snapshot and the compromise event (seq 0) have arrived when
    // status polling reports "finished" — the final event (seq 1) is still
    // in flight.
    ws.push(snapshotFrame);
    ws.push(compromiseFrame);

    await vi.advanceTimersByTimeAsync(1000); // first poll: running
    await vi.advanceTimersByTimeAsync(1000); // second poll: finished, last_seq=1

    // Give the catch-up loop a few ticks to run — it must keep waiting
    // since lastSeq (0) hasn't reached last_seq (1) yet.
    await vi.advanceTimersByTimeAsync(60);

    // Now the final event actually arrives.
    ws.push(otherEventFrame);
    await vi.advanceTimersByTimeAsync(20);

    const result = await resultPromise;

    expect(result.metrics).toEqual(METRICS_RESPONSE);
  });

  it("gives up waiting and reports metrics fetched over REST if the socket closes before catching up", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "POST" && String(url).endsWith("/api/experiments")) {
        return okResponse(summary("running"));
      }
      if (method === "GET" && String(url).endsWith(`/api/experiments/${EXPERIMENT_ID}/metrics`)) {
        return okResponse(METRICS_RESPONSE);
      }
      if (method === "GET" && String(url).endsWith(`/api/experiments/${EXPERIMENT_ID}`)) {
        return okResponse(summary("finished", 5));
      }
      if (method === "POST" && String(url).endsWith(`/api/experiments/${EXPERIMENT_ID}/stop`)) {
        return okResponse(summary("stopped"));
      }
      throw new Error(`unexpected fetch call: ${method} ${url}`);
    });

    const resultPromise = runExperimentToCompletion(CONFIG);
    await vi.advanceTimersByTimeAsync(0);
    const ws = FakeWebSocket.instances[0];
    ws.push(snapshotFrame);
    ws.push(compromiseFrame);
    ws.onclose?.();

    await vi.advanceTimersByTimeAsync(1000);

    const result = await resultPromise;
    expect(result.metrics).toEqual(METRICS_RESPONSE);
  });

  it("rejects when the AbortSignal fires, and still best-effort stops the experiment and closes the WS", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "POST" && String(url).endsWith("/api/experiments")) {
        return okResponse(summary("running"));
      }
      if (method === "GET" && String(url).endsWith(`/api/experiments/${EXPERIMENT_ID}`)) {
        return okResponse(summary("running"));
      }
      if (method === "POST" && String(url).endsWith(`/api/experiments/${EXPERIMENT_ID}/stop`)) {
        return okResponse(summary("stopped"));
      }
      throw new Error(`unexpected fetch call: ${method} ${url}`);
    });

    const controller = new AbortController();
    const resultPromise = runExperimentToCompletion(CONFIG, { signal: controller.signal });

    await vi.advanceTimersByTimeAsync(0);
    expect(FakeWebSocket.instances).toHaveLength(1);
    const ws = FakeWebSocket.instances[0];

    const assertion = expect(resultPromise).rejects.toMatchObject({ name: "AbortError" });

    controller.abort();

    await assertion;
    await vi.advanceTimersByTimeAsync(0);

    const stopCalls = callsMatching("POST", `/api/experiments/${EXPERIMENT_ID}/stop`);
    expect(stopCalls).toHaveLength(1);
    expect(ws.closed).toBe(true);
  });

  it("rejects immediately (still stopping and closing) when the signal is already aborted before the run starts", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "POST" && String(url).endsWith("/api/experiments")) {
        return okResponse(summary("running"));
      }
      if (method === "GET" && String(url).endsWith(`/api/experiments/${EXPERIMENT_ID}`)) {
        return okResponse(summary("running"));
      }
      if (method === "POST" && String(url).endsWith(`/api/experiments/${EXPERIMENT_ID}/stop`)) {
        return okResponse(summary("stopped"));
      }
      throw new Error(`unexpected fetch call: ${method} ${url}`);
    });

    const controller = new AbortController();
    controller.abort();

    const resultPromise = runExperimentToCompletion(CONFIG, { signal: controller.signal });

    await expect(resultPromise).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(0);

    const stopCalls = callsMatching("POST", `/api/experiments/${EXPERIMENT_ID}/stop`);
    expect(stopCalls).toHaveLength(1);
    expect(FakeWebSocket.instances[0]?.closed).toBe(true);
  });
});
