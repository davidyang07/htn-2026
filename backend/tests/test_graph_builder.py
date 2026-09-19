from app.engine.topology import build_world
from app.graph.builder import build_security_graph
from app.graph.types import EdgeType, NodeType
from app.schemas.experiment import ExperimentConfig


def _world(**overrides):
    config = ExperimentConfig(seed=42, node_count=25, **overrides)
    world, _ = build_world(config)
    return world, config


def test_default_config_yields_agent_only_graph_mirroring_world_state():
    world, config = _world()
    graph = build_security_graph(world, config)

    assert {n.id for n in graph.nodes_of_type(NodeType.AGENT)} == set(world.nodes)
    assert not graph.nodes_of_type(NodeType.TOOL)
    assert not graph.nodes_of_type(NodeType.CREDENTIAL)
    assert not graph.nodes_of_type(NodeType.RESOURCE)
    assert not graph.nodes_of_type(NodeType.SENTINEL)
    assert not graph.nodes_of_type(NodeType.SECURITY_CONTROL)

    comm = frozenset({EdgeType.COMMUNICATES_WITH})
    comm_edges = {(e.source, e.target) for e in graph.edges(comm)}
    expected = set()
    for a, b in world.edges:
        expected.add((a, b))
        expected.add((b, a))
    assert comm_edges == expected


def test_trust_edges_mirror_communication_topology_with_default_weight():
    world, config = _world()
    graph = build_security_graph(world, config)

    trust = graph.edges(frozenset({EdgeType.TRUSTS}))
    trust_edges = {(e.source, e.target): e.attrs["weight"] for e in trust}
    comm = graph.edges(frozenset({EdgeType.COMMUNICATES_WITH}))
    comm_pairs = {(e.source, e.target) for e in comm}
    assert set(trust_edges) == comm_pairs
    assert all(weight == 1.0 for weight in trust_edges.values())


def test_tools_attach_to_a_subset_of_agents():
    world, config = _world(tool_count=3)
    graph = build_security_graph(world, config)

    tool_ids = {n.id for n in graph.nodes_of_type(NodeType.TOOL)}
    assert tool_ids == {"tool-000", "tool-001", "tool-002"}
    can_access = graph.edges(frozenset({EdgeType.CAN_ACCESS}))
    accessed_tools = {e.target for e in can_access if e.target in tool_ids}
    assert accessed_tools == tool_ids


def test_credentials_attach_to_one_holder_and_unlock_a_resource():
    world, config = _world(credential_count=2, resource_count=1)
    graph = build_security_graph(world, config)

    uses = graph.edges(frozenset({EdgeType.USES_CREDENTIAL}))
    assert {e.source for e in uses} <= set(world.nodes)
    assert {e.target for e in uses} == {"credential-000", "credential-001"}

    unlocks = graph.edges(frozenset({EdgeType.CAN_ACCESS}))
    credential_to_resource = {
        e.source: e.target for e in unlocks if e.source.startswith("credential-")
    }
    assert credential_to_resource == {
        "credential-000": "resource-000",
        "credential-001": "resource-000",
    }


def test_credentials_with_no_resources_have_no_dangling_access_edge():
    world, config = _world(credential_count=1, resource_count=0)
    graph = build_security_graph(world, config)
    assert not graph.nodes_of_type(NodeType.RESOURCE)
    can_access = graph.edges(frozenset({EdgeType.CAN_ACCESS}))
    unlocks = [e for e in can_access if e.source == "credential-000"]
    assert unlocks == []


def test_sentinels_get_monitoring_and_quarantine_authority_and_security_controls():
    world, config = _world(sentinel_count=2)
    graph = build_security_graph(world, config)

    sentinel_ids = {n.id for n in graph.nodes_of_type(NodeType.SENTINEL)}
    assert sentinel_ids == {"sentinel-000", "sentinel-001"}

    control_kinds = {n.attrs["kind"] for n in graph.nodes_of_type(NodeType.SECURITY_CONTROL)}
    assert control_kinds == {
        "trust_manager",
        "threat_memory_store",
        "attestation_service",
        "quarantine_authority",
    }

    monitors = graph.edges(frozenset({EdgeType.MONITORS}))
    monitored_agents = {e.target for e in monitors}
    assert monitored_agents == set(world.nodes)
    assert {e.source for e in monitors} == sentinel_ids

    authority = graph.edges(frozenset({EdgeType.QUARANTINE_AUTHORITY}))
    assert {e.target for e in authority} == set(world.nodes)
    assert {e.source for e in authority} == {"control-quarantine"}

    threat_memory = graph.edges(frozenset({EdgeType.UPDATES_THREAT_MEMORY}))
    assert {e.source for e in threat_memory if e.target == "control-threat-memory"} == sentinel_ids


def test_zero_sentinels_yields_no_security_plane_nodes():
    world, config = _world(sentinel_count=0)
    graph = build_security_graph(world, config)
    assert not graph.nodes_of_type(NodeType.SENTINEL)
    assert not graph.nodes_of_type(NodeType.SECURITY_CONTROL)


def test_build_security_graph_is_deterministic_across_calls():
    world, config = _world(tool_count=2, credential_count=2, resource_count=1, sentinel_count=1)

    graph_a = build_security_graph(world, config)
    graph_b = build_security_graph(world, config)

    edges_a = sorted((e.source, e.target, e.edge_type) for e in graph_a.edges())
    edges_b = sorted((e.source, e.target, e.edge_type) for e in graph_b.edges())
    assert edges_a == edges_b
    assert {n.id for n in graph_a.nodes} == {n.id for n in graph_b.nodes}
