import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MetricsResponse } from "@/lib/api/client";

import { loadHistoricalArm } from "./loadHistoricalArm";

const EXPERIMENT_ID = "exp-hist-1";

function okResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body } as Response;
}

const METRICS_RESPONSE: MetricsResponse = {
  compromise_fraction: 0.2,
  retained_utility: 0.7,
  blast_radius_fraction: 0.3,
  privileged_exposure: 2,
  security_plane_integrity: 1,
  attack_success_rate: 0.4,
  false_quarantine_rate: 0,
  detection_latency: 1,
  containment_latency: 2,
};

describe("loadHistoricalArm", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches the reconstructed MetricsResponse over REST and reports incomplete=false", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      const u = String(url);
      if (u.endsWith("/detail")) return okResponse({ is_complete: true });
      if (u.endsWith("/replay/metrics")) return okResponse(METRICS_RESPONSE);
      throw new Error(`unexpected fetch: ${u}`);
    });

    const result = await loadHistoricalArm(EXPERIMENT_ID);

    expect(result.experimentId).toBe(EXPERIMENT_ID);
    expect(result.incomplete).toBe(false);
    expect(result.metrics).toEqual(METRICS_RESPONSE);
  });

  it("reports incomplete=true for a run whose persisted record never proved a gapless seq range", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      const u = String(url);
      if (u.endsWith("/detail")) return okResponse({ is_complete: false });
      if (u.endsWith("/replay/metrics")) return okResponse(METRICS_RESPONSE);
      throw new Error(`unexpected fetch: ${u}`);
    });

    const result = await loadHistoricalArm(EXPERIMENT_ID);
    expect(result.incomplete).toBe(true);
  });
});
