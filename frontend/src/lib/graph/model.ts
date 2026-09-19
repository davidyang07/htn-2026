import type { SecurityGraphView } from "@/lib/api/client";
import type { GraphState, NodeView } from "@/lib/stream/reducer";
import { SECURITY_STATE_SEVERITY, SEVERITY_HEX, type SecurityState } from "@/lib/severity";
import { EDGE_LAYER_OF, type EdgeLayer, type GraphEdgeType } from "@/lib/vocabulary";

export type TopologyNode = {
  id: string;
  nodeType: string;
  securityState: SecurityState;
  attrs: Record<string, unknown>;
};

export type TopologyEdge = { source: string; target: string; edgeType: string };

export type TopologyModel = {
  /** Changes only when the *structure* changes, so the expensive layout runs
   * once per run rather than on every 2s poll. */
  structureKey: string;
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  /** True when only the agent mesh is known — the security graph has not
   * loaded yet, or the run declared no typed non-agent nodes. */
  meshOnly: boolean;
};

/**
 * The topology the graph renders. Structure comes from the security graph
 * (the only source that knows about tools, credentials and sentinels);
 * agent security state is overlaid from the live WebSocket stream, which is
 * an order of magnitude fresher than the 2s REST poll.
 */
export function buildTopologyModel(
  securityGraph: SecurityGraphView | null,
  stream: GraphState,
): TopologyModel {
  const liveStates = new Map<string, NodeView>();
  for (const node of stream.nodes.values()) liveStates.set(node.id, node);

  if (!securityGraph) {
    const nodes: TopologyNode[] = [...stream.nodes.values()].map((node) => ({
      id: node.id,
      nodeType: "agent",
      securityState: node.security_state,
      attrs: { software_type: node.software_type, agent_kind: node.agent_kind },
    }));
    const edges: TopologyEdge[] = stream.edges.map((edge) => ({
      source: edge.source,
      target: edge.target,
      edgeType: "communicates_with",
    }));
    return {
      structureKey: `stream:${stream.experimentId ?? "none"}:${nodes.length}:${edges.length}`,
      nodes,
      edges,
      meshOnly: true,
    };
  }

  const nodes: TopologyNode[] = securityGraph.nodes.map((node) => {
    const live = liveStates.get(node.id);
    return {
      id: node.id,
      nodeType: node.node_type,
      securityState: (live?.security_state ?? node.security_state) as SecurityState,
      attrs: {
        ...node.attrs,
        ...(live ? { software_type: live.software_type, agent_kind: live.agent_kind } : {}),
      },
    };
  });

  const edges: TopologyEdge[] = securityGraph.edges.map((edge) => ({
    source: edge.source,
    target: edge.target,
    edgeType: edge.edge_type,
  }));

  return {
    structureKey: `graph:${stream.experimentId ?? "none"}:${nodes.length}:${edges.length}`,
    nodes,
    edges,
    meshOnly: nodes.every((n) => n.nodeType === "agent"),
  };
}

// --- Visual encoding ------------------------------------------------------
//
// Colour is reserved for security state (SPEC §4). Node *type* therefore gets
// its own two channels — outline shape and size — which is what lets a
// compromised sentinel and a compromised agent be told apart at a glance
// while both correctly reading as red.

export type NodeShape = "circle" | "square" | "diamond" | "hexagon" | "triangle" | "shield";

export const NODE_SHAPE: Record<string, NodeShape> = {
  agent: "circle",
  tool: "square",
  mcp_server: "square",
  credential: "diamond",
  resource: "hexagon",
  memory_store: "hexagon",
  sentinel: "triangle",
  security_control: "shield",
};

/** Sigma node sizes, in graph units. Non-agent nodes are larger because there
 * are far fewer of them and each one carries more meaning. */
export const NODE_SIZE: Record<string, number> = {
  agent: 3.4,
  tool: 5,
  mcp_server: 5.4,
  credential: 5.2,
  resource: 5.6,
  memory_store: 5,
  sentinel: 6.6,
  security_control: 6,
};

export function nodeShape(nodeType: string): NodeShape {
  return NODE_SHAPE[nodeType] ?? "circle";
}

export function nodeSize(node: TopologyNode): number {
  const base = NODE_SIZE[node.nodeType] ?? 4;
  // Size, not colour, is also how LLM-backed ("real") agents are distinguished
  // from simulated ones (docs/PHASE_2_PLAN.md §11).
  if (node.nodeType === "agent" && node.attrs.agent_kind === "real") return base * 1.5;
  return base;
}

export function nodeColor(node: TopologyNode): string {
  return SEVERITY_HEX[SECURITY_STATE_SEVERITY[node.securityState] ?? "neutral"];
}

export function edgeLayer(edgeType: string): EdgeLayer {
  return EDGE_LAYER_OF[edgeType as GraphEdgeType] ?? "mesh";
}

/**
 * Deduplicates the graph's edges for rendering. The backend emits both
 * directions of `communicates_with` *and* a parallel `trusts` pair for every
 * agent link — four edges where the picture only ever wants one line.
 */
export function renderableEdges(edges: TopologyEdge[], layers: ReadonlySet<EdgeLayer>): TopologyEdge[] {
  const seen = new Set<string>();
  const out: TopologyEdge[] = [];
  for (const edge of edges) {
    if (edge.source === edge.target) continue;
    const layer = edgeLayer(edge.edgeType);
    if (!layers.has(layer)) continue;
    const [a, b] = edge.source < edge.target ? [edge.source, edge.target] : [edge.target, edge.source];
    const key = `${layer}:${a}:${b}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(edge);
  }
  return out;
}

/** Adjacency over the mesh layer only — what "neighbours" means when the
 * question is who a compromise can reach next. */
export function meshNeighbors(edges: TopologyEdge[], nodeId: string): string[] {
  const out = new Set<string>();
  for (const edge of edges) {
    if (edgeLayer(edge.edgeType) !== "mesh") continue;
    if (edge.source === nodeId) out.add(edge.target);
    else if (edge.target === nodeId) out.add(edge.source);
  }
  return [...out].sort();
}

/** Every node one hop away on any layer, with the edge type that connects it —
 * the node inspector's "what does this touch" list. */
export function incidentEdges(edges: TopologyEdge[], nodeId: string): TopologyEdge[] {
  const seen = new Set<string>();
  const out: TopologyEdge[] = [];
  for (const edge of edges) {
    if (edge.source !== nodeId && edge.target !== nodeId) continue;
    const other = edge.source === nodeId ? edge.target : edge.source;
    const key = `${edge.edgeType}:${other}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(edge);
  }
  return out;
}
