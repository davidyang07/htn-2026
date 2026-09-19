import uuid

from app.engine.propagation import step
from app.engine.simulate import run_full
from app.engine.state import AgentNode, SecurityState, WorldState
from app.events.emitter import EventEmitter
from app.schemas.experiment import ExperimentConfig


def _run(seed: int) -> list[tuple]:
    config = ExperimentConfig(seed=seed, node_count=25, max_ticks=10)
    drafts = run_full(config)
    events = EventEmitter(experiment_id=uuid.uuid4()).emit(drafts)
    return [
        (
            e.seq,
            e.sim_tick,
            e.event_type,
            e.agent_id,
            e.source_agent_id,
            e.target_agent_id,
            e.metadata,
        )
        for e in events
    ]


def test_two_full_runs_same_seed_are_identical():
    a = _run(42)
    b = _run(42)
    assert a == b
    assert len(a) > 0


def test_different_seed_differs():
    assert _run(42) != _run(43)


# --- Golden fixture: 5 nodes, hand-picked topology, 3 ticks, seed=42 ---
# Hand-derived from SPEC §3.4 by inspection (see the M0 plan, §8) before this
# test was written. Exercises the §3.4 rule 6 same-tick multi-source tiebreak
# at agent-001 in tick=2 (agent-000 claims, agent-004's success is marked
# already_compromised).


def _golden_world() -> WorldState:
    ids = [f"agent-{i:03d}" for i in range(5)]
    types = {ids[i]: ("sw-a" if i % 2 == 0 else "sw-b") for i in range(5)}
    edges = [
        ("agent-004", "agent-001"),
        ("agent-004", "agent-002"),
        ("agent-004", "agent-003"),
        ("agent-001", "agent-000"),
        ("agent-002", "agent-000"),
    ]
    neighbors: dict[str, set[str]] = {n: set() for n in ids}
    for a, b in edges:
        neighbors[a].add(b)
        neighbors[b].add(a)

    seed_node = "agent-004"
    nodes = {}
    for n in ids:
        state = SecurityState.COMPROMISED if n == seed_node else SecurityState.HEALTHY
        nodes[n] = AgentNode(
            id=n,
            software_type=types[n],
            security_state=state,
            neighbors=tuple(sorted(neighbors[n])),
            compromised_by=None,
            tick_compromised=0 if n == seed_node else None,
        )
    edge_tuples = tuple(sorted((a, b) if a < b else (b, a) for a, b in edges))
    return WorldState(tick=0, nodes=nodes, edges=edge_tuples)


def test_propagation_golden_fixture_tiebreak():
    world = _golden_world()
    config = ExperimentConfig.model_construct(
        seed=42,
        node_count=5,
        edge_density=2,
        software_type_count=2,
        p_same=0.4,
        p_cross=0.2,
        max_ticks=3,
    )

    expected = [
        (0, "COMPROMISE_ATTEMPTED", "agent-004", "agent-001", {"probability": 0.2}),
        (0, "COMPROMISE_FAILED", "agent-004", "agent-001", {"probability": 0.2}),
        (0, "COMPROMISE_ATTEMPTED", "agent-004", "agent-002", {"probability": 0.4}),
        (0, "COMPROMISE_SUCCEEDED", "agent-004", "agent-002", {"probability": 0.4}),
        (0, "COMPROMISE_ATTEMPTED", "agent-004", "agent-003", {"probability": 0.2}),
        (0, "COMPROMISE_FAILED", "agent-004", "agent-003", {"probability": 0.2}),
        (1, "COMPROMISE_ATTEMPTED", "agent-002", "agent-000", {"probability": 0.4}),
        (1, "COMPROMISE_SUCCEEDED", "agent-002", "agent-000", {"probability": 0.4}),
        (1, "COMPROMISE_ATTEMPTED", "agent-004", "agent-001", {"probability": 0.2}),
        (1, "COMPROMISE_FAILED", "agent-004", "agent-001", {"probability": 0.2}),
        (1, "COMPROMISE_ATTEMPTED", "agent-004", "agent-003", {"probability": 0.2}),
        (1, "COMPROMISE_SUCCEEDED", "agent-004", "agent-003", {"probability": 0.2}),
        (2, "COMPROMISE_ATTEMPTED", "agent-000", "agent-001", {"probability": 0.2}),
        (2, "COMPROMISE_SUCCEEDED", "agent-000", "agent-001", {"probability": 0.2}),
        (2, "COMPROMISE_ATTEMPTED", "agent-004", "agent-001", {"probability": 0.2}),
        (
            2,
            "COMPROMISE_SUCCEEDED",
            "agent-004",
            "agent-001",
            {"probability": 0.2, "already_compromised": True},
        ),
    ]

    actual: list[tuple] = []
    for _ in range(3):
        world, drafts = step(world, config)
        for d in drafts:
            actual.append(
                (d.sim_tick, d.event_type.value, d.source_agent_id, d.target_agent_id, d.metadata)
            )

    assert actual == expected

    final = {n: world.nodes[n] for n in world.nodes}
    assert all(a.security_state == SecurityState.COMPROMISED for a in final.values())
    assert final["agent-004"].compromised_by is None
    assert final["agent-002"].compromised_by == "agent-004"
    assert final["agent-003"].compromised_by == "agent-004"
    assert final["agent-000"].compromised_by == "agent-002"
    assert final["agent-001"].compromised_by == "agent-000"  # tiebreak: not agent-004
    assert final["agent-004"].tick_compromised == 0
    assert final["agent-002"].tick_compromised == 0
    assert final["agent-003"].tick_compromised == 1
    assert final["agent-000"].tick_compromised == 1
    assert final["agent-001"].tick_compromised == 2
