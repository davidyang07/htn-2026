import asyncio

from app.engine.simulate import run_full
from app.engine.state import AgentNode, SecurityState, WorldState
from app.orchestrator.runner import ExperimentRunner
from app.schemas.events import EventType
from app.schemas.experiment import ExperimentConfig
from app.security.detection import step

# --- Golden fixture: 5 nodes, seed=42, tick=1, detector_sensitivity=0.8 ---
# Hand-derived by calling the existing rng() primitive directly (see the M1
# plan, §4/§10) before this test was written and confirmed against SPEC:
#   rng(42, 1, "agent-000", "detect").random() == 0.2484588835063859  (< 0.8 -> detected)
#   rng(42, 1, "agent-001", "detect").random() == 0.8304344241049259  (>= 0.8 -> not detected)
#   rng(42, 1, "agent-002", "detect").random() == 0.7578711207834954  (< 0.8 -> detected)


def _detection_world() -> WorldState:
    states = {
        "agent-000": SecurityState.COMPROMISED,
        "agent-001": SecurityState.COMPROMISED,
        "agent-002": SecurityState.COMPROMISED,
        "agent-003": SecurityState.HEALTHY,
        "agent-004": SecurityState.QUARANTINED,
    }
    nodes = {
        n: AgentNode(
            id=n,
            software_type="sw-a",
            security_state=state,
            neighbors=(),
            compromised_by=None,
            tick_compromised=None if state == SecurityState.HEALTHY else 0,
        )
        for n, state in states.items()
    }
    return WorldState(tick=1, nodes=nodes, edges=())


def test_golden_fixture_detection_order_and_transitions():
    world = _detection_world()
    config = ExperimentConfig(seed=42, detector_sensitivity=0.8, defense_enabled=True)

    new_world, drafts = step(world, config)

    actual = [(d.sim_tick, d.event_type.value, d.agent_id, d.metadata) for d in drafts]
    expected = [
        (1, "ANOMALY_DETECTED", "agent-000", {"sensitivity": 0.8}),
        (1, "AGENT_QUARANTINED", "agent-000", {}),
        (1, "ANOMALY_DETECTED", "agent-002", {"sensitivity": 0.8}),
        (1, "AGENT_QUARANTINED", "agent-002", {}),
    ]
    assert actual == expected
    assert all(d.risk_score is None for d in drafts)

    assert new_world.nodes["agent-000"].security_state == SecurityState.QUARANTINED
    assert new_world.nodes["agent-001"].security_state == SecurityState.COMPROMISED
    assert new_world.nodes["agent-002"].security_state == SecurityState.QUARANTINED
    assert new_world.nodes["agent-003"].security_state == SecurityState.HEALTHY
    assert new_world.nodes["agent-004"].security_state == SecurityState.QUARANTINED
    assert new_world.tick == 1


def test_defense_disabled_returns_unchanged_state_and_no_drafts():
    world = _detection_world()
    config = ExperimentConfig(seed=42, detector_sensitivity=0.8, defense_enabled=False)

    new_world, drafts = step(world, config)

    assert new_world == world
    assert drafts == []


def test_defense_disabled_run_full_produces_zero_detection_events():
    config = ExperimentConfig(
        seed=7, node_count=30, max_ticks=15, defense_enabled=False
    )
    drafts = run_full(config)

    assert all(
        d.event_type.value not in ("ANOMALY_DETECTED", "AGENT_QUARANTINED")
        for d in drafts
    )


def test_quarantined_node_never_source_or_target_after_quarantine():
    config = ExperimentConfig(
        seed=7, node_count=30, max_ticks=25, defense_enabled=True, detector_sensitivity=0.5
    )
    drafts = run_full(config)

    quarantined_at_index: dict[str, int] = {}
    for i, d in enumerate(drafts):
        if d.event_type.value == "AGENT_QUARANTINED":
            quarantined_at_index[d.agent_id] = i

    assert quarantined_at_index, "expected at least one quarantine in this run"

    propagation_types = ("COMPROMISE_ATTEMPTED", "COMPROMISE_SUCCEEDED", "COMPROMISE_FAILED")
    for i, d in enumerate(drafts):
        if d.event_type.value not in propagation_types:
            continue
        for node in (d.source_agent_id, d.target_agent_id):
            if node in quarantined_at_index:
                assert i <= quarantined_at_index[node], (
                    f"{node} acted as source/target at draft index {i} "
                    f"after being quarantined at draft index {quarantined_at_index[node]}"
                )


def test_live_runner_uses_same_detection_pipeline_as_run_full():
    config = ExperimentConfig(
        seed=7,
        node_count=25,
        max_ticks=1,
        defense_enabled=True,
        detector_sensitivity=1.0,
    )
    expected = [
        (
            draft.sim_tick,
            draft.event_type,
            draft.agent_id,
            draft.source_agent_id,
            draft.target_agent_id,
            draft.metadata,
        )
        for draft in run_full(config)
    ]

    async def run_live() -> list[tuple]:
        runner = ExperimentRunner(config)
        runner.tick_interval = 0
        await runner.publish_initial()
        await runner._run_loop()
        events = runner.bus.since(-1)
        assert events is not None
        return [
            (
                event.sim_tick,
                event.event_type,
                event.agent_id,
                event.source_agent_id,
                event.target_agent_id,
                event.metadata,
            )
            for event in events
        ]

    actual = asyncio.run(run_live())

    assert actual == expected
    assert any(event_type == EventType.AGENT_QUARANTINED for _, event_type, *_ in actual)
