from app.engine.state import SecurityState
from app.engine.topology import build_world_from_agents
from app.schemas.experiment import ExperimentConfig


def test_build_world_from_agents_assigns_software_types_round_robin():
    config = ExperimentConfig(seed=1, node_count=25, software_type_count=2)
    agent_ids = ["alpha", "beta", "gamma"]
    edges = {("alpha", "beta"), ("beta", "gamma")}
    world, drafts = build_world_from_agents(agent_ids, edges, config)
    assert set(world.nodes) == {"alpha", "beta", "gamma"}
    assert world.nodes["alpha"].software_type == "sw-a"
    assert world.nodes["beta"].software_type == "sw-b"
    assert world.nodes["gamma"].software_type == "sw-a"
    assert world.nodes["alpha"].neighbors == ("beta",)
    assert world.nodes["beta"].neighbors == ("alpha", "gamma")
    assert drafts[0].event_type.value == "AGENT_CREATED"


def test_build_world_from_agents_seeds_exactly_one_compromise():
    config = ExperimentConfig(seed=1, node_count=25)
    agent_ids = ["alpha", "beta", "gamma"]
    edges = {("alpha", "beta"), ("beta", "gamma")}
    world, _ = build_world_from_agents(agent_ids, edges, config)
    compromised = [
        n for n in world.nodes.values() if n.security_state == SecurityState.COMPROMISED
    ]
    assert len(compromised) == 1


def test_build_world_from_agents_highest_degree_is_beta():
    config = ExperimentConfig(seed=1, node_count=25, initial_compromised="highest_degree")
    agent_ids = ["alpha", "beta", "gamma"]
    edges = {("alpha", "beta"), ("beta", "gamma")}
    world, _ = build_world_from_agents(agent_ids, edges, config)
    assert world.nodes["beta"].security_state == SecurityState.COMPROMISED


def test_build_world_from_agents_is_deterministic():
    config = ExperimentConfig(seed=1, node_count=25)
    agent_ids = ["alpha", "beta", "gamma"]
    edges = {("alpha", "beta"), ("beta", "gamma")}
    world1, _ = build_world_from_agents(agent_ids, edges, config)
    world2, _ = build_world_from_agents(agent_ids, edges, config)
    assert {n: s.security_state for n, s in world1.nodes.items()} == {
        n: s.security_state for n, s in world2.nodes.items()
    }
