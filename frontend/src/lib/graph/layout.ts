import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";

import { EDGE_LAYER_OF, nodeTypeMeta, type GraphEdgeType } from "@/lib/vocabulary";

export type LayoutNode = { id: string; nodeType: string };
export type LayoutEdge = { source: string; target: string; edgeType: string };
export type Point = { x: number; y: number };

const FORCE_ATLAS2_ITERATIONS = 300;

// Golden angle — a deterministic, evenly-spread seeding of the initial
// positions. Replaces the previous `Math.random()` seeding, which made the
// layout differ between two runs of the same seed even though SPEC §4 calls
// for positions "stable across reruns of the same seed".
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

/** Distance from the centre of the agent cloud at which each plane's ring sits. */
const PLANE_RADIUS: Record<string, number> = {
  workload: 1.3,
  data: 1.56,
  security: 1.84,
};

/**
 * Two-stage layout, because one force pass over the whole typed graph reads
 * badly: `control-quarantine` alone has an edge to every agent, so a single
 * ForceAtlas2 run collapses the agent mesh around it and hides the structure
 * the mesh is there to show.
 *
 * Stage 1 lays out the agent mesh alone with ForceAtlas2 — the topology that
 * compromise actually propagates through.
 * Stage 2 places every non-agent node on a ring outside that cloud, ordered by
 * the mean direction of the agents it attaches to, so tools/credentials stay
 * near the agents that reach them while never overlapping each other.
 *
 * Pure and deterministic: the same inputs always produce the same positions.
 */
export function computeLayout(nodes: LayoutNode[], edges: LayoutEdge[]): Map<string, Point> {
  const positions = new Map<string, Point>();
  const agents = nodes.filter((n) => n.nodeType === "agent");
  if (agents.length === 0) {
    placeOnCircle(nodes.map((n) => n.id).sort(), 1, positions);
    return positions;
  }

  const agentIds = new Set(agents.map((n) => n.id));

  const mesh = new Graph({ type: "undirected", multi: false });
  agents.forEach((node, index) => {
    // sqrt keeps the seeded spiral area-uniform rather than centre-heavy.
    const radius = Math.sqrt((index + 0.5) / agents.length);
    const angle = index * GOLDEN_ANGLE;
    mesh.addNode(node.id, { x: radius * Math.cos(angle), y: radius * Math.sin(angle) });
  });
  for (const edge of edges) {
    if (EDGE_LAYER_OF[edge.edgeType as GraphEdgeType] !== "mesh") continue;
    if (!agentIds.has(edge.source) || !agentIds.has(edge.target)) continue;
    if (edge.source === edge.target) continue;
    if (!mesh.hasEdge(edge.source, edge.target)) mesh.addEdge(edge.source, edge.target);
  }

  if (mesh.size > 0) {
    forceAtlas2.assign(mesh, {
      iterations: FORCE_ATLAS2_ITERATIONS,
      settings: { ...forceAtlas2.inferSettings(mesh), adjustSizes: false },
    });
  }

  // Normalise the agent cloud to a unit disc centred on the origin, so the
  // ring radii below mean the same thing whatever ForceAtlas2 produced.
  let sumX = 0;
  let sumY = 0;
  mesh.forEachNode((_id, attrs) => {
    sumX += attrs.x as number;
    sumY += attrs.y as number;
  });
  const centreX = sumX / mesh.order;
  const centreY = sumY / mesh.order;
  let maxRadius = 0;
  mesh.forEachNode((_id, attrs) => {
    const dx = (attrs.x as number) - centreX;
    const dy = (attrs.y as number) - centreY;
    maxRadius = Math.max(maxRadius, Math.hypot(dx, dy));
  });
  const scale = maxRadius > 0 ? 1 / maxRadius : 1;
  mesh.forEachNode((id, attrs) => {
    positions.set(id, {
      x: ((attrs.x as number) - centreX) * scale,
      y: ((attrs.y as number) - centreY) * scale,
    });
  });

  // Stage 2: rings, one per plane.
  const attachments = new Map<string, string[]>();
  for (const edge of edges) {
    if (agentIds.has(edge.source) && !agentIds.has(edge.target)) {
      push(attachments, edge.target, edge.source);
    } else if (agentIds.has(edge.target) && !agentIds.has(edge.source)) {
      push(attachments, edge.source, edge.target);
    }
  }

  const byPlane = new Map<string, LayoutNode[]>();
  for (const node of nodes) {
    if (agentIds.has(node.id)) continue;
    const plane = nodeTypeMeta(node.nodeType).plane;
    push(byPlane, plane, node as never);
  }

  for (const [plane, planeNodes] of byPlane) {
    const withAngle = planeNodes
      .map((node) => ({ node, angle: meanAngle(attachments.get(node.id) ?? [], positions) }))
      // Sort by preferred direction, tie-broken by id, so the result is stable.
      .sort((a, b) => a.angle - b.angle || a.node.id.localeCompare(b.node.id));
    const radius = PLANE_RADIUS[plane] ?? 1.4;
    // Evenly spaced on the ring, in preferred-direction order: keeps each
    // node near the agents it serves without ever letting two collide.
    withAngle.forEach(({ node }, index) => {
      const angle = (index / withAngle.length) * Math.PI * 2;
      positions.set(node.id, { x: radius * Math.cos(angle), y: radius * Math.sin(angle) });
    });
  }

  // Anything unplaced (an edge-less node of an unknown type) still needs a
  // position, or Sigma will refuse to render the graph at all.
  const unplaced = nodes.filter((n) => !positions.has(n.id)).map((n) => n.id);
  if (unplaced.length > 0) placeOnCircle(unplaced, 2.1, positions);

  return positions;
}

function push<K, V>(map: Map<K, V[]>, key: K, value: V): void {
  const existing = map.get(key);
  if (existing) existing.push(value);
  else map.set(key, [value]);
}

/** Circular mean of the directions of `neighbours` from the origin. Returns a
 * value in [0, 2π); an empty set maps to 0 so ordering stays deterministic. */
function meanAngle(neighbours: string[], positions: Map<string, Point>): number {
  let sumX = 0;
  let sumY = 0;
  for (const id of neighbours) {
    const point = positions.get(id);
    if (!point) continue;
    const length = Math.hypot(point.x, point.y) || 1;
    sumX += point.x / length;
    sumY += point.y / length;
  }
  if (sumX === 0 && sumY === 0) return 0;
  const angle = Math.atan2(sumY, sumX);
  return angle < 0 ? angle + Math.PI * 2 : angle;
}

function placeOnCircle(ids: string[], radius: number, into: Map<string, Point>): void {
  ids.forEach((id, index) => {
    const angle = (index / Math.max(1, ids.length)) * Math.PI * 2;
    into.set(id, { x: radius * Math.cos(angle), y: radius * Math.sin(angle) });
  });
}
