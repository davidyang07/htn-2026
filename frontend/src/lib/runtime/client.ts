// The Live Swarm Demo's transport (docs/MVP_PLAN.md P0.12).
//
// Kept separate from lib/api/client.ts's experiment functions because the live
// runtime is a peer of the simulator, not a mode of it: different lifecycle,
// different registry, different screen. The *shapes* are shared — these types
// come out of the same generated schema.d.ts — only the endpoints are new.

import type { components } from "@/lib/api/schema.d.ts";

export type RuntimeSessionSummary = components["schemas"]["RuntimeSessionSummary"];
export type WorkerView = components["schemas"]["WorkerView"];
export type ArtifactView = components["schemas"]["ArtifactView"];
export type RuntimeEventPage = components["schemas"]["RuntimeEventPage"];
export type IncidentExplanation = components["schemas"]["IncidentExplanation"];
export type RuntimeResetResponse = components["schemas"]["RuntimeResetResponse"];
export type SnapshotFrame = components["schemas"]["SnapshotFrame"];
export type WorkflowState = RuntimeSessionSummary["workflow_state"];

// AgentShield's own port is configurable because WorkSwarm also defaults to
// 8000 (docs/DEMO.md §1). These two env vars already existed for the
// simulator; the demo just needs them pointed at whichever port AgentShield
// was started on.
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const BACKEND_WS_URL = process.env.NEXT_PUBLIC_BACKEND_WS_URL ?? "ws://localhost:8000";

/** Distinguishes "no live session yet" (the idle screen) from a real failure. */
export class NoLiveSessionError extends Error {
  constructor() {
    super("no live runtime session");
    this.name = "NoLiveSessionError";
  }
}

export async function getCurrentRuntimeSession(
  signal?: AbortSignal,
): Promise<RuntimeSessionSummary> {
  const res = await fetch(`${BACKEND_URL}/api/runtime/sessions/current`, {
    signal,
    cache: "no-store",
  });
  if (res.status === 404) {
    throw new NoLiveSessionError();
  }
  if (!res.ok) {
    throw new Error(`failed to get the live runtime session: ${res.status}`);
  }
  return res.json();
}

export async function getRuntimeSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<RuntimeSessionSummary> {
  const res = await fetch(`${BACKEND_URL}/api/runtime/sessions/${sessionId}`, {
    signal,
    cache: "no-store",
  });
  if (res.status === 404) {
    throw new NoLiveSessionError();
  }
  if (!res.ok) {
    throw new Error(`failed to get runtime session: ${res.status}`);
  }
  return res.json();
}

/** The same SnapshotFrame the socket sends on connect. */
export async function getRuntimeSnapshot(
  sessionId: string,
  signal?: AbortSignal,
): Promise<SnapshotFrame> {
  const res = await fetch(`${BACKEND_URL}/api/runtime/sessions/${sessionId}/snapshot`, {
    signal,
    cache: "no-store",
  });
  if (res.status === 404) {
    throw new NoLiveSessionError();
  }
  if (!res.ok) {
    throw new Error(`failed to get the runtime snapshot: ${res.status}`);
  }
  return res.json();
}

/** Everything still in the session's replay buffer, oldest first. */
export async function getRuntimeEvents(
  sessionId: string,
  sinceSeq = -1,
  signal?: AbortSignal,
): Promise<RuntimeEventPage> {
  const url = new URL(`${BACKEND_URL}/api/runtime/sessions/${sessionId}/events`);
  url.searchParams.set("since_seq", String(sinceSeq));
  const res = await fetch(url, { signal, cache: "no-store" });
  if (res.status === 404) {
    throw new NoLiveSessionError();
  }
  if (!res.ok) {
    throw new Error(`failed to get runtime events: ${res.status}`);
  }
  return res.json();
}

export async function getRuntimeExplanation(
  sessionId: string,
  signal?: AbortSignal,
): Promise<IncidentExplanation> {
  const res = await fetch(`${BACKEND_URL}/api/runtime/sessions/${sessionId}/explanation`, {
    signal,
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`failed to get the incident explanation: ${res.status}`);
  }
  return res.json();
}

/** Reset Demo. Drops every live session; the simulator is untouched. */
export async function resetRuntimeSessions(): Promise<RuntimeResetResponse> {
  const res = await fetch(`${BACKEND_URL}/api/runtime/sessions`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`failed to reset the demo: ${res.status}`);
  }
  return res.json();
}

export function runtimeWsUrl(sessionId: string, sinceSeq?: number): string {
  const url = new URL(`${BACKEND_WS_URL}/api/runtime/sessions/${sessionId}/stream`);
  if (sinceSeq !== undefined) {
    url.searchParams.set("since_seq", String(sinceSeq));
  }
  return url.toString();
}
