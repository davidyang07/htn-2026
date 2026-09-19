from pathlib import Path

from app.engine.propagation import is_finished
from app.engine.tick import advance
from app.engine.topology import build_world_from_agents
from app.graph.builder import build_security_graph
from app.importers.external_topology import (
    attach_tool_bindings,
    load_topology_json,
    tag_sentinel_agents,
)
from app.metrics.compute import compromise_fraction, security_plane_integrity
from app.schemas.experiment import ExperimentConfig

TOPOLOGY_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "examples"
    / "langgraph_research_agents"
    / "topology.json"
)


def test_committed_topology_json_exists():
    assert TOPOLOGY_PATH.exists(), "run examples/langgraph_research_agents/export_topology.py first"


def test_imported_topology_runs_an_adversarial_scenario_end_to_end():
    topology = load_topology_json(TOPOLOGY_PATH)
    config = ExperimentConfig(
        # node_count is unused by build_world_from_agents (the real agent
        # ids/edges below are what actually build the topology) but is
        # still validated on construction (ge=25) -- any in-bounds value
        # works.
        seed=42,
        node_count=25,
        sentinel_count=1,
        active_scenarios=["propagation", "sentinel_compromise"],
        defense_enabled=True,
    )
    world, _ = build_world_from_agents(
        topology.agents, {tuple(e) for e in topology.edges}, config
    )

    while not is_finished(world, config):
        world, _ = advance(world, config)

    graph = build_security_graph(world, config)
    attach_tool_bindings(graph, topology.tool_bindings)
    tag_sentinel_agents(graph, topology.sentinel_agents)

    assert 0.0 <= compromise_fraction(world) <= 1.0
    assert any(n.id.startswith("tool-") for n in graph.nodes)
    assert 0.0 <= security_plane_integrity(graph) <= 1.0


def test_imported_topology_matches_the_committed_result_artifact():
    """Pins the real measured numbers in backend/.artifacts/external_import/
    result.json -- regenerate that artifact (`make import-demo`) and update
    this test together if a deliberate engine/scenario change legitimately
    moves these numbers; a silent drift here means the importer or the
    scenario composition broke, not that the pin is stale."""
    topology = load_topology_json(TOPOLOGY_PATH)
    config = ExperimentConfig(
        seed=42,
        node_count=25,
        sentinel_count=1,
        sentinel_compromise_rate=0.3,
        active_scenarios=["propagation", "sentinel_compromise"],
        defense_enabled=True,
    )
    world, _ = build_world_from_agents(
        topology.agents, {tuple(e) for e in topology.edges}, config
    )
    while not is_finished(world, config):
        world, _ = advance(world, config)
    graph = build_security_graph(world, config)

    assert compromise_fraction(world) == 1.0
    assert security_plane_integrity(graph) == 0.8
