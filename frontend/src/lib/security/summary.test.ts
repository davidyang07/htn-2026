import { describe, expect, it } from "vitest";

import type { SecurityGraphView } from "@/lib/api/client";
import { exposedAssets, summarizeNonAgentNodes, tallySecurityStates, worstSeverity } from "./summary";

function graphNode(id: string, node_type: string, security_state = "healthy") {
  return { id, node_type, security_state, attrs: {} } as SecurityGraphView["nodes"][number];
}

describe("summarizeNonAgentNodes", () => {
  it("excludes agent nodes", () => {
    const graph: SecurityGraphView = {
      nodes: [graphNode("agent-000", "agent"), graphNode("tool-000", "tool")],
      edges: [],
    };
    expect(summarizeNonAgentNodes(graph).map((s) => s.nodeType)).toEqual(["tool"]);
  });

  it("counts total and compromised nodes per type", () => {
    const graph: SecurityGraphView = {
      nodes: [
        graphNode("sentinel-000", "sentinel", "compromised"),
        graphNode("sentinel-001", "sentinel", "healthy"),
        graphNode("credential-000", "credential", "compromised"),
      ],
      edges: [],
    };
    expect(summarizeNonAgentNodes(graph)).toEqual([
      { nodeType: "credential", total: 1, compromised: 1 },
      { nodeType: "sentinel", total: 2, compromised: 1 },
    ]);
  });

  it("returns an empty array for a graph with only agents", () => {
    const graph: SecurityGraphView = { nodes: [graphNode("agent-000", "agent")], edges: [] };
    expect(summarizeNonAgentNodes(graph)).toEqual([]);
  });

  it("sorts by node type name", () => {
    const graph: SecurityGraphView = {
      nodes: [graphNode("tool-000", "tool"), graphNode("credential-000", "credential")],
      edges: [],
    };
    expect(summarizeNonAgentNodes(graph).map((s) => s.nodeType)).toEqual(["credential", "tool"]);
  });
});

describe("tallySecurityStates", () => {
  const graph: SecurityGraphView = {
    nodes: [
      graphNode("agent-000", "agent", "compromised"),
      graphNode("agent-001", "agent", "healthy"),
      graphNode("agent-002", "agent", "healthy"),
      graphNode("sentinel-000", "sentinel", "compromised"),
    ],
    edges: [],
  };

  it("counts every node's state when no type filter is given", () => {
    expect(tallySecurityStates(graph)).toEqual({ compromised: 2, healthy: 2 });
  });

  it("restricts the tally to one node type", () => {
    expect(tallySecurityStates(graph, "agent")).toEqual({ compromised: 1, healthy: 2 });
  });
});

describe("worstSeverity", () => {
  it("returns the worst state present, not the most common", () => {
    expect(worstSeverity(["healthy", "healthy", "compromised"])).toBe("critical");
    expect(worstSeverity(["healthy", "quarantined"])).toBe("contained");
    expect(worstSeverity(["healthy"])).toBe("neutral");
  });

  it("returns neutral for an empty set", () => {
    expect(worstSeverity([])).toBe("neutral");
  });
});

describe("exposedAssets", () => {
  const graph: SecurityGraphView = {
    nodes: [
      graphNode("agent-000", "agent", "compromised"),
      graphNode("credential-000", "credential", "compromised"),
      graphNode("credential-001", "credential"),
      graphNode("resource-000", "resource"),
      graphNode("tool-000", "tool"),
    ],
    edges: [],
  };

  it("returns only credential and resource nodes inside the reachable set", () => {
    expect(exposedAssets(graph, ["agent-000", "credential-000", "resource-000", "tool-000"])).toEqual([
      { id: "credential-000", nodeType: "credential", securityState: "compromised" },
      { id: "resource-000", nodeType: "resource", securityState: "healthy" },
    ]);
  });

  it("returns nothing when no asset is reachable", () => {
    expect(exposedAssets(graph, ["agent-000"])).toEqual([]);
  });
});
