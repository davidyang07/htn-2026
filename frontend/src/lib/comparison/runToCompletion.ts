import {
  createExperiment,
  getExperiment,
  getMetrics,
  stopExperiment,
  backendWsUrl,
  type ExperimentConfig,
  type MetricsResponse,
} from "@/lib/api/client";
import { reduce, initialGraphState, type GraphState, type StreamFrame } from "@/lib/stream/reducer";

const STATUS_POLL_INTERVAL_MS = 1000;
// Once REST reports a terminal status, the WS delivery of the final tick's
// events is not guaranteed to have already landed (they're independent
// connections) — poll local catch-up at this cadence rather than sampling
// once.
const CATCH_UP_POLL_MS = 20;
// Bound on how long to wait for WS to catch up to the terminal `last_seq`
// before giving up and reporting whatever's been observed — avoids hanging
// forever if the socket died without a final close/error callback firing.
const CATCH_UP_TIMEOUT_MS = 5000;

export type RunResult = {
  experimentId: string;
  metrics: MetricsResponse;
};

/**
 * Headless (non-React) helper that creates an experiment, observes it live
 * over WS (feeding every frame through the same pure `reduce()` the
 * dashboard's `useExperimentStream` hook uses), and detects natural
 * completion via REST polling of `getExperiment` — WS alone never surfaces
 * a status change on natural finish, so polling is the only reliable
 * terminal-state signal (see the equivalent status-poll `useEffect` in
 * `app/page.tsx`).
 *
 * On both the success path and the cancellation (AbortSignal) path,
 * `stopExperiment` is called best-effort after the outcome is otherwise
 * determined, and the WebSocket is always closed.
 */
export async function runExperimentToCompletion(
  config: ExperimentConfig,
  opts?: { signal?: AbortSignal },
): Promise<RunResult> {
  const summary = await createExperiment(config);
  const experimentId = summary.experiment_id;

  let graphState: GraphState = initialGraphState;
  let socketOpen = true;
  const ws = new WebSocket(backendWsUrl(experimentId));
  ws.onmessage = (ev) => {
    const frame = JSON.parse(ev.data as string) as StreamFrame;
    graphState = reduce(graphState, frame);
  };
  ws.onclose = () => {
    socketOpen = false;
  };

  let finalLastSeq: number | null = null;

  try {
    finalLastSeq = await new Promise<number>((resolve, reject) => {
      if (opts?.signal?.aborted) {
        reject(new DOMException("Aborted", "AbortError"));
        return;
      }
      let cancelled = false;
      let timer: ReturnType<typeof setTimeout>;

      const cleanup = () => {
        cancelled = true;
        clearTimeout(timer);
        opts?.signal?.removeEventListener("abort", onAbort);
      };
      function onAbort() {
        cleanup();
        reject(new DOMException("Aborted", "AbortError"));
      }
      opts?.signal?.addEventListener("abort", onAbort);

      const poll = () => {
        if (cancelled) return;
        getExperiment(experimentId)
          .then((s) => {
            if (cancelled) return;
            if (s.status === "finished" || s.status === "stopped") {
              cleanup();
              resolve(s.last_seq);
            } else {
              timer = setTimeout(poll, STATUS_POLL_INTERVAL_MS);
            }
          })
          .catch(() => {
            if (!cancelled) timer = setTimeout(poll, STATUS_POLL_INTERVAL_MS);
          });
      };
      timer = setTimeout(poll, STATUS_POLL_INTERVAL_MS);
    });
  } catch (err) {
    // Deviates from a bare try/finally: the cancellation path must still
    // best-effort stop the experiment (guarantee 3), which a plain
    // try/finally can't do since a rejection would skip the code after it.
    ws.close();
    await stopExperiment(experimentId).catch(() => {});
    throw err;
  }

  // The backend reports "finished"/"stopped" as soon as its own event
  // publish for the final tick has been awaited — but that only guarantees
  // the events reached the bus, not that this independent WS connection has
  // already received and applied them (they're actually always at least
  // one full tick_interval ahead by construction, but that's not an
  // architectural guarantee). Wait for the locally-observed seq to catch up
  // to the terminal summary's last_seq before treating metrics as final, so
  // a comparison arm's numbers can never be sampled mid-delivery.
  const deadline = Date.now() + CATCH_UP_TIMEOUT_MS;
  while (graphState.lastSeq < finalLastSeq && socketOpen && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, CATCH_UP_POLL_MS));
  }

  ws.close();
  // The rich MetricsResponse (security-plane/remediation-relevant fields)
  // is fetched over REST rather than derived from selectMetrics(graphState)
  // -- the same live /metrics endpoint the dashboard's insights already poll
  // -- so a live comparison arm and a historical one (loadHistoricalArm.ts)
  // report the exact same metric shape (docs/PLAN.md §9's "Next
  // recommended milestone"). Fetched before stopExperiment so the runner
  // is still registered.
  const metrics = await getMetrics(experimentId);
  await stopExperiment(experimentId).catch(() => {});
  return { experimentId, metrics };
}
