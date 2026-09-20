// The swarm graph's structure, built from the session summary rather than the
// stream.
//
// Why not `buildTopologyModel(null, stream)`: the shared stream reducer creates
// nodes only from a *snapshot*, never from an `AGENT_CREATED` event — which is
// correct for the simulator, where the whole world exists at tick 0. A live
// swarm grows a worker mid-run, so a client that attached before the
// Replacement Researcher was created would never draw it, and "a new worker
// joins and takes over" is the part of the demo that matters most.
//
// So: structure comes from the summary (authoritative and always complete),
// and security state is overlaid from the stream when it has an opinion,
// because the socket is an order of magnitude fresher than the poll. Exactly
// the split `buildTopologyModel` already makes for the simulator's typed graph.

import type { RuntimeSessionSummary } from "@/lib/runtime/client";
import type { SecurityState } from "@/lib/severity";
import type { TopologyModel, TopologyNode, TopologyEdge } from "@/lib/graph/model";
import type { GraphState } from "@/lib/stream/reducer";

export function buildSwarmModel(
  summary: RuntimeSessionSummary | null,
  stream: GraphState,
): TopologyModel {
  if (!summary) {
    return { structureKey: "swarm:none", nodes: [], edges: [], meshOnly: true };
  }

  const live = stream.experimentId === summary.session_id ? stream.nodes : null;

  const nodes: TopologyNode[] = summary.workers.map((worker) => ({
    id: worker.id,
    nodeType: "agent",
    securityState: (live?.get(worker.id)?.security_state ??
      worker.security_state) as SecurityState,
    attrs: {
      software_type: worker.role,
      agent_kind: "real",
      replaces: worker.replaces,
      model_backed: worker.model_backed,
    },
  }));

  const known = new Set(nodes.map((n) => n.id));
  const seen = new Set<string>();
  const edges: TopologyEdge[] = [];

  function add(source: string, target: string) {
    if (!known.has(source) || !known.has(target)) return;
    const key = `${source}|${target}`;
    if (seen.has(key)) return;
    seen.add(key);
    edges.push({ source, target, edgeType: "delegates_to" });
  }

  for (const worker of summary.workers) {
    for (const upstream of worker.upstream ?? []) add(upstream, worker.id);
  }

  // A replacement inherits the handoffs of the worker it took over from, so
  // the graph shows the team routing around the quarantined node. Downstream
  // workers declared their upstream at creation and cannot re-declare it.
  for (const worker of summary.workers) {
    if (!worker.replaces) continue;
    for (const other of summary.workers) {
      if ((other.upstream ?? []).includes(worker.replaces)) add(worker.id, other.id);
    }
  }

  return {
    // Only the *structure* keys the layout, so the expensive ForceAtlas2 pass
    // runs when a worker joins — not on every 1.5s poll or every event.
    structureKey: `swarm:${summary.session_id}:${nodes.length}:${edges.length}`,
    nodes,
    edges,
    meshOnly: true,
  };
}
