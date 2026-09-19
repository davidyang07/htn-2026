"""Exports graph_app's compiled LangGraph topology to topology.json, the
schema AgentShield's backend/app/importers/external_topology.py reads. Run this
with LangGraph actually installed (`pip install -r requirements.txt`)
whenever graph_app.py's structure changes; topology.json is committed so
AgentShield's tests/scripts never need LangGraph installed to consume it.
"""

import json
from pathlib import Path

from graph_app import SENTINEL_AGENTS, TOOL_BINDINGS, build_graph

OUTPUT = Path(__file__).parent / "topology.json"

NON_AGENT_NODES = {"__start__", "__end__"}


def main() -> None:
    app = build_graph()
    nx_graph = app.get_graph()

    agents = sorted(n for n in nx_graph.nodes if n not in NON_AGENT_NODES)
    edges = sorted(
        {
            tuple(sorted((edge.source, edge.target)))
            for edge in nx_graph.edges
            if edge.source not in NON_AGENT_NODES and edge.target not in NON_AGENT_NODES
        }
    )

    topology = {
        "agents": agents,
        "edges": [list(e) for e in edges],
        "tool_bindings": TOOL_BINDINGS,
        "sentinel_agents": SENTINEL_AGENTS,
    }
    OUTPUT.write_text(json.dumps(topology, indent=2) + "\n")
    print(f"Wrote {OUTPUT}: {len(agents)} agents, {len(edges)} edges")


if __name__ == "__main__":
    main()
