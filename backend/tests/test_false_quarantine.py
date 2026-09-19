from app.engine.rng import rng
from app.engine.state import AgentNode, SecurityState, WorldState
from app.schemas.experiment import ExperimentConfig
from app.security.detection import step


def _world(states: dict[str, SecurityState]) -> WorldState:
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


def test_zero_rate_is_a_strict_noop():
    world = _world({"agent-000": SecurityState.HEALTHY})
    config = ExperimentConfig(seed=42, defense_enabled=True, false_quarantine_rate=0.0)

    new_world, drafts = step(world, config)

    assert drafts == []
    assert new_world == world


def test_full_rate_falsely_quarantines_every_healthy_node_with_no_prior_detection():
    world = _world(
        {"agent-000": SecurityState.HEALTHY, "agent-001": SecurityState.HEALTHY}
    )
    config = ExperimentConfig(
        seed=42, defense_enabled=True, detector_sensitivity=0.0, false_quarantine_rate=1.0
    )

    new_world, drafts = step(world, config)

    assert len(drafts) == 2
    for draft in drafts:
        assert draft.event_type.value == "AGENT_QUARANTINED"
        assert draft.metadata == {"legitimate": False}
    assert {d.agent_id for d in drafts} == {"agent-000", "agent-001"}
    assert new_world.nodes["agent-000"].security_state == SecurityState.QUARANTINED
    assert new_world.nodes["agent-001"].security_state == SecurityState.QUARANTINED
    # The defining violation: no ANOMALY_DETECTED precedes it.
    assert not any(d.event_type.value == "ANOMALY_DETECTED" for d in drafts)


def test_does_not_affect_compromised_or_already_quarantined_nodes():
    world = _world(
        {
            "agent-000": SecurityState.COMPROMISED,
            "agent-001": SecurityState.QUARANTINED,
            "agent-002": SecurityState.HEALTHY,
        }
    )
    config = ExperimentConfig(
        seed=42, defense_enabled=True, detector_sensitivity=0.0, false_quarantine_rate=1.0
    )

    new_world, drafts = step(world, config)

    false_quarantine_targets = {d.agent_id for d in drafts if d.metadata.get("legitimate") is False}
    assert false_quarantine_targets == {"agent-002"}
    assert new_world.nodes["agent-000"].security_state == SecurityState.COMPROMISED


def test_disabled_defense_is_still_a_noop_even_with_nonzero_rate():
    world = _world({"agent-000": SecurityState.HEALTHY})
    config = ExperimentConfig(seed=42, defense_enabled=False, false_quarantine_rate=1.0)

    new_world, drafts = step(world, config)

    assert drafts == []
    assert new_world == world


def test_is_keyed_deterministically_and_independent_of_legitimate_draws():
    world = _world({"agent-000": SecurityState.HEALTHY})
    config = ExperimentConfig(seed=42, defense_enabled=True, false_quarantine_rate=0.5)

    expected = rng(config.seed, world.tick, "agent-000", "false_quarantine").random() < 0.5

    _, drafts = step(world, config)

    assert bool(drafts) == expected


def test_is_deterministic_across_calls():
    world = _world(
        {f"agent-{i:03d}": SecurityState.HEALTHY for i in range(10)}
    )
    config = ExperimentConfig(seed=7, defense_enabled=True, false_quarantine_rate=0.4)

    world_a, drafts_a = step(world, config)
    world_b, drafts_b = step(world, config)

    assert world_a == world_b
    assert drafts_a == drafts_b
