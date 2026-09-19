#!/usr/bin/env python3
"""Runs an adversarial scenario against the real LangGraph sample app's
imported topology (Priority 3: real external multi-agent integration).
Requires examples/langgraph_research_agents/topology.json to already exist
(committed; regenerate via that directory's export_topology.py if the
sample app changes).
"""

import json
from pathlib import Path
from uuid import uuid4

from app.engine.propagation import is_finished
from app.engine.tick import advance
from app.engine.topology import build_world_from_agents
from app.events.emitter import EventEmitter
from app.graph.builder import build_security_graph
from app.importers.external_topology import (
    attach_tool_bindings,
    load_topology_json,
    tag_sentinel_agents,
)
from app.metrics import compute as metrics
from app.remediation.analyze import recommend
from app.schemas.experiment import ExperimentConfig

TOPOLOGY_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "examples"
    / "langgraph_research_agents"
    / "topology.json"
)
ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / ".artifacts" / "external_import"


def main() -> int:
    topology = load_topology_json(TOPOLOGY_PATH)
    config = ExperimentConfig(
        seed=42,
        node_count=25,  # unused by build_world_from_agents; only validated on construction
        sentinel_count=1,
        sentinel_compromise_rate=0.3,
        active_scenarios=["propagation", "sentinel_compromise"],
        defense_enabled=True,
    )
    world, drafts = build_world_from_agents(
        topology.agents, {tuple(e) for e in topology.edges}, config
    )

    while not is_finished(world, config):
        world, tick_drafts = advance(world, config)
        drafts.extend(tick_drafts)

    events = EventEmitter(experiment_id=uuid4()).emit(drafts)
    graph = build_security_graph(world, config)
    attach_tool_bindings(graph, topology.tool_bindings)
    tag_sentinel_agents(graph, topology.sentinel_agents)

    run_metrics = {
        "compromise_fraction": metrics.compromise_fraction(world),
        "retained_utility": metrics.retained_utility(world),
        "security_plane_integrity": metrics.security_plane_integrity(graph),
        "attack_success_rate": metrics.attack_success_rate(events),
    }
    recs = recommend(
        config,
        compromise_fraction=run_metrics["compromise_fraction"],
        security_plane_integrity=run_metrics["security_plane_integrity"],
    )

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS_DIR / "result.json").write_text(
        json.dumps(
            {
                "imported_agents": topology.agents,
                "metrics": run_metrics,
                "remediation": [r.description for r in recs],
            },
            indent=2,
        )
    )

    print(f"Imported {len(topology.agents)} agents from {TOPOLOGY_PATH}")
    print(json.dumps(run_metrics, indent=2))
    for r in recs:
        print(f"Remediation: {r.description}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
