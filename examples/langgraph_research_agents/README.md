# LangGraph research-agents sample app

A small, real [LangGraph](https://github.com/langchain-ai/langgraph) multi-agent pipeline:
`research_agent` calls `web_search_tool`, hands its findings to `summarizer_agent`, which reports
to `sentinel_agent`. This is the external application AgentShield's importer
(`backend/app/importers/external_topology.py`) ingests and adversarially evaluates — see
`backend/scripts/run_external_import_demo.py`.

This is a genuinely separate small Python project — it is never added to `backend/pyproject.toml`,
so AgentShield's backend has no LangGraph runtime dependency.

## Regenerating `topology.json`

`topology.json` (committed) is AgentShield's import format: agent ids, communication edges, tool
bindings, and which agents play a sentinel/overseer role. It's produced by actually calling
LangGraph's own `compiled_graph.get_graph()` API, not hand-written, so it reflects the real
compiled graph structure. Regenerate it whenever `graph_app.py` changes:

```bash
cd examples/langgraph_research_agents
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python export_topology.py
```

## What AgentShield does with it

`backend/scripts/run_external_import_demo.py` loads the committed `topology.json` (no LangGraph
install required for this step — it's a plain JSON file), builds an AgentShield `WorldState` from the
real agent ids and communication edges via `build_world_from_agents`, attaches the real tool
bindings as `CAN_ACCESS` edges, tags `sentinel_agent` with its imported role, then runs an
adversarial scenario (propagation + sentinel compromise) against it and computes metrics and
remediation recommendations — exactly like any AgentShield-native experiment.
