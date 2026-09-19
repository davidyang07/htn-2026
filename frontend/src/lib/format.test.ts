import { describe, expect, it } from "vitest";
import type { EdgeView, NodeView } from "@/lib/stream/reducer";
import {
  deriveNeighbors,
  describeCompromisedBy,
  describeTickCompromised,
  formatConfigDiff,
  formatEventMetadata,
  formatLatency,
  formatPercent,
  formatProvenanceChain,
  shortId,
} from "./format";

function node(overrides: Partial<NodeView> & Pick<NodeView, "id">): NodeView {
  return {
    software_type: "sw-a",
    security_state: "healthy",
    agent_kind: "simulated",
    ...overrides,
  };
}

describe("deriveNeighbors", () => {
  it("returns neighbor ids where the node is source, target, or excludes unrelated edges", () => {
    const edges: EdgeView[] = [
      { source: "agent-000", target: "agent-001" }, // node is source
      { source: "agent-002", target: "agent-000" }, // node is target
      { source: "agent-003", target: "agent-004" }, // unrelated
    ];

    expect(deriveNeighbors("agent-000", edges)).toEqual(["agent-001", "agent-002"]);
  });
});

describe("describeCompromisedBy", () => {
  it("returns the unknown qualifier for a compromised node with null compromised_by", () => {
    const n = node({ id: "agent-000", security_state: "compromised", compromised_by: null });
    expect(describeCompromisedBy(n)).toBe("unknown (before this session's connection)");
  });

  it("returns the unknown qualifier for a quarantined node with null compromised_by", () => {
    const n = node({ id: "agent-000", security_state: "quarantined", compromised_by: null });
    expect(describeCompromisedBy(n)).toBe("unknown (before this session's connection)");
  });

  it("labels the seeded patient-zero node (tick_compromised 0, no source) distinctly from lost data", () => {
    const n = node({
      id: "agent-000",
      security_state: "compromised",
      compromised_by: null,
      tick_compromised: 0,
    });
    expect(describeCompromisedBy(n)).toBe("— (initial compromise)");
  });

  it("still returns the actual agent id when compromised_by is non-null", () => {
    const n = node({
      id: "agent-000",
      security_state: "compromised",
      compromised_by: "agent-002",
    });
    expect(describeCompromisedBy(n)).toBe("agent-002");
  });

  it("returns an em dash for a healthy node with null compromised_by", () => {
    const n = node({ id: "agent-000", security_state: "healthy", compromised_by: null });
    expect(describeCompromisedBy(n)).toBe("—");
  });
});

describe("describeTickCompromised", () => {
  it("mirrors describeCompromisedBy's unknown qualifier when the source was never observed", () => {
    const n = node({
      id: "agent-000",
      security_state: "compromised",
      compromised_by: null,
      tick_compromised: 5,
    });
    expect(describeTickCompromised(n)).toBe("unknown (before this session's connection)");
  });

  it("returns the recorded tick for a normally observed compromise", () => {
    const n = node({
      id: "agent-000",
      security_state: "compromised",
      compromised_by: "agent-002",
      tick_compromised: 7,
    });
    expect(describeTickCompromised(n)).toBe("7");
  });

  it("returns the seeded patient-zero tick rather than the unknown qualifier", () => {
    const n = node({
      id: "agent-000",
      security_state: "compromised",
      compromised_by: null,
      tick_compromised: 0,
    });
    expect(describeTickCompromised(n)).toBe("0");
  });

  it("returns an em dash for a healthy node", () => {
    expect(describeTickCompromised(node({ id: "agent-000" }))).toBe("—");
  });
});

describe("formatPercent", () => {
  it("rounds a fraction to a whole-number percent", () => {
    expect(formatPercent(0.5)).toBe("50%");
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(1)).toBe("100%");
    expect(formatPercent(0.336)).toBe("34%");
  });
});

describe("formatLatency", () => {
  it("returns an em dash for null or undefined", () => {
    expect(formatLatency(null)).toBe("—");
    expect(formatLatency(undefined)).toBe("—");
  });

  it("formats a numeric latency to one decimal with a unit", () => {
    expect(formatLatency(2)).toBe("2.0 ticks");
    expect(formatLatency(2.567)).toBe("2.6 ticks");
  });
});

describe("formatConfigDiff", () => {
  it("returns a placeholder for an empty diff", () => {
    expect(formatConfigDiff({})).toBe("(no change)");
  });

  it("formats a single-key diff", () => {
    expect(formatConfigDiff({ sentinel_count: 2 })).toBe("sentinel_count → 2");
  });

  it("formats a multi-key diff joined by commas", () => {
    expect(formatConfigDiff({ defense_enabled: true, detector_sensitivity: 0.4 })).toBe(
      "defense_enabled → true, detector_sensitivity → 0.4",
    );
  });
});

describe("formatProvenanceChain", () => {
  it("joins a chain with arrows", () => {
    expect(formatProvenanceChain(["agent-000", "agent-004", "agent-012"])).toBe(
      "agent-000 → agent-004 → agent-012",
    );
  });

  it("returns a placeholder for an empty chain", () => {
    expect(formatProvenanceChain([])).toBe("(no provenance chain)");
  });
});

describe("formatEventMetadata", () => {
  it("returns an empty string for absent or empty metadata", () => {
    expect(formatEventMetadata(null)).toBe("");
    expect(formatEventMetadata(undefined)).toBe("");
    expect(formatEventMetadata({})).toBe("");
  });

  it("renders key=value pairs without JSON braces, leaving strings unquoted", () => {
    expect(formatEventMetadata({ probability: 0.03, strategy: "stealthy" })).toBe(
      "probability=0.03  strategy=stealthy",
    );
  });
});

describe("shortId", () => {
  it("truncates a uuid to its first segment", () => {
    expect(shortId("645c39d3-60cd-4ab9-83dc-e41823ccc8c6")).toBe("645c39d3");
  });
});
