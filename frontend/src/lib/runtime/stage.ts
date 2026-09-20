// The causal layout of the swarm, for the incident stage.
//
// A force-directed graph is the wrong instrument here. It is excellent at
// "what does this 400-node mesh look like", and useless at the only question
// /demo has to answer: *who handed work to whom, and where did that chain
// break*. Five nodes in a physics simulation land somewhere different every
// run, put the quarantined worker wherever the springs settle, and give a
// judge nothing to follow.
//
// So the stage is laid out deterministically from the handoff DAG the session
// already reports: column = depth in the chain, and a replacement sits in the
// same column as the worker it took over from, directly beneath it. The
// picture is therefore identical every run, and the reassignment reads as a
// vertical drop inside one column rather than as an edge crossing the canvas.

import type { RuntimeSessionSummary, WorkerView } from "@/lib/runtime/client";
import type { SecurityState } from "@/lib/severity";
import type { GraphState } from "@/lib/stream/reducer";

export type StageNode = {
  id: string;
  role: string;
  securityState: SecurityState;
  currentTask: string | null;
  quarantineReason: string | null;
  /** The worker this one took over from, if it is a replacement. */
  replaces: string | null;
  modelBacked: boolean;
  /** Depth in the handoff chain. Replacements inherit their predecessor's. */
  column: number;
};

export type StageColumn = {
  column: number;
  /** Original worker first, then whatever replaced it. */
  nodes: StageNode[];
};

export type Stage = {
  columns: StageColumn[];
  /** Quarantined worker id → the replacement that took its task. */
  reassignments: ReadonlyMap<string, string>;
  /** True once any worker in the swarm is quarantined. */
  breached: boolean;
};

export const EMPTY_STAGE: Stage = {
  columns: [],
  reassignments: new Map(),
  breached: false,
};

/**
 * Depth of each worker in the handoff chain.
 *
 * Iterative rather than recursive, and capped by the worker count, because
 * `upstream` is reported by a live swarm and nothing in the protocol promises
 * it is acyclic. A cycle must not hang the screen.
 */
function depths(workers: readonly WorkerView[]): Map<string, number> {
  const byId = new Map(workers.map((w) => [w.id, w]));
  const depth = new Map<string, number>();

  for (let pass = 0; pass < workers.length + 1; pass += 1) {
    let changed = false;
    for (const worker of workers) {
      // A replacement belongs beside the worker it replaced, not one step
      // further down the chain: it did not receive that worker's output, it
      // received its *task*.
      const parents =
        worker.replaces !== null && worker.replaces !== undefined
          ? [worker.replaces]
          : (worker.upstream ?? []);

      let next = 0;
      for (const parentId of parents) {
        if (!byId.has(parentId)) continue;
        if (worker.replaces === parentId) {
          next = Math.max(next, depth.get(parentId) ?? 0);
        } else {
          next = Math.max(next, (depth.get(parentId) ?? 0) + 1);
        }
      }
      if (depth.get(worker.id) !== next) {
        depth.set(worker.id, next);
        changed = true;
      }
    }
    if (!changed) break;
  }

  return depth;
}

export function buildStage(
  summary: RuntimeSessionSummary | null,
  stream: GraphState,
): Stage {
  if (!summary || summary.workers.length === 0) return EMPTY_STAGE;

  // Security state comes from the socket when it has an opinion about this
  // session — it is an order of magnitude fresher than the 1.5s poll — and
  // from the summary otherwise. The same split `buildSwarmModel` makes.
  const live = stream.experimentId === summary.session_id ? stream.nodes : null;
  const depth = depths(summary.workers);

  const nodes: StageNode[] = summary.workers.map((worker) => ({
    id: worker.id,
    role: worker.role,
    securityState: (live?.get(worker.id)?.security_state ??
      worker.security_state) as SecurityState,
    currentTask: worker.current_task ?? null,
    quarantineReason: worker.quarantine_reason ?? null,
    replaces: worker.replaces ?? null,
    modelBacked: worker.model_backed,
    column: depth.get(worker.id) ?? 0,
  }));

  const order = new Map(nodes.map((node, index) => [node.id, index]));
  const grouped = new Map<number, StageNode[]>();
  for (const node of nodes) {
    const bucket = grouped.get(node.column);
    if (bucket) bucket.push(node);
    else grouped.set(node.column, [node]);
  }

  const columns: StageColumn[] = [...grouped.entries()]
    .sort(([a], [b]) => a - b)
    .map(([column, group]) => ({
      column,
      nodes: group.sort((a, b) => {
        // A replacement always renders below the worker it replaced, whatever
        // order the registry happens to report them in.
        if (a.replaces === b.id) return 1;
        if (b.replaces === a.id) return -1;
        return (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0);
      }),
    }));

  const reassignments = new Map<string, string>();
  for (const node of nodes) {
    if (node.replaces) reassignments.set(node.replaces, node.id);
  }

  return {
    columns,
    reassignments,
    breached: nodes.some((node) => node.securityState === "quarantined"),
  };
}
