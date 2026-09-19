from app.engine.rng import rng
from app.engine.state import AgentNode, SecurityState, WorldState
from app.scenarios.attestation_scenario import step
from app.schemas.experiment import ExperimentConfig


def _world(tick: int = 5) -> WorldState:
    nodes = {
        "agent-000": AgentNode(
            id="agent-000",
            software_type="sw-a",
            security_state=SecurityState.COMPROMISED,
            neighbors=("agent-001",),
            tick_compromised=0,
        ),
        "agent-001": AgentNode(
            id="agent-001",
            software_type="sw-a",
            security_state=SecurityState.HEALTHY,
            neighbors=("agent-000",),
        ),
    }
    return WorldState(tick=tick, nodes=nodes, edges=(("agent-000", "agent-001"),))


def test_zero_rate_is_a_strict_noop():
    world = _world()
    config = ExperimentConfig(seed=42, sentinel_count=1, attestation_replay_rate=0.0)

    new_world, drafts = step(world, config)

    assert drafts == []
    assert new_world == world


def test_no_sentinels_means_no_attestation_service_and_is_a_noop():
    world = _world()
    config = ExperimentConfig(seed=42, sentinel_count=0, attestation_replay_rate=1.0)

    _, drafts = step(world, config)

    assert drafts == []


def test_full_rate_replays_a_stale_nonce_for_every_compromised_agent():
    world = _world(tick=5)
    config = ExperimentConfig(seed=42, sentinel_count=1, attestation_replay_rate=1.0)

    new_world, drafts = step(world, config)

    issued = [d for d in drafts if d.event_type.value == "ATTESTATION_ISSUED"]
    verified = [d for d in drafts if d.event_type.value == "ATTESTATION_VERIFIED"]
    assert len(issued) == 1
    assert len(verified) == 1
    assert issued[0].agent_id == "agent-000"
    assert issued[0].metadata["nonce"] == 4
    assert verified[0].metadata == {"nonce": 4, "replayed": True}
    assert new_world == world


def test_zero_rate_of_replay_uses_the_current_tick_as_nonce():
    world = _world(tick=5)
    config = ExperimentConfig(seed=1, sentinel_count=1, attestation_replay_rate=0.0001)
    # attestation_replay_rate must be > 0 to run at all; use a rate whose draw
    # is virtually certain to exceed it, then assert the non-replay shape.
    draw = rng(config.seed, world.tick, "agent-000", "attestation_replay").random()
    assert draw >= config.attestation_replay_rate  # sanity: this draw is "not replayed"

    _, drafts = step(world, config)

    verified = [d for d in drafts if d.event_type.value == "ATTESTATION_VERIFIED"][0]
    assert verified.metadata == {"nonce": 5, "replayed": False}


def test_only_compromised_agents_attempt_attestation():
    world = _world()
    config = ExperimentConfig(seed=42, sentinel_count=1, attestation_replay_rate=1.0)

    _, drafts = step(world, config)

    agent_ids = {d.agent_id for d in drafts}
    assert agent_ids == {"agent-000"}


def test_tick_zero_replay_clamps_nonce_to_zero_not_negative():
    world = _world(tick=0)
    config = ExperimentConfig(seed=42, sentinel_count=1, attestation_replay_rate=1.0)

    _, drafts = step(world, config)

    issued = [d for d in drafts if d.event_type.value == "ATTESTATION_ISSUED"][0]
    assert issued.metadata["nonce"] == 0


def test_does_not_own_the_tick_increment():
    world = _world()
    config = ExperimentConfig(seed=42, sentinel_count=1, attestation_replay_rate=1.0)

    new_world, _ = step(world, config)

    assert new_world.tick == world.tick


def test_is_deterministic_across_calls():
    world = _world()
    config = ExperimentConfig(seed=7, sentinel_count=1, attestation_replay_rate=0.5)

    _, drafts_a = step(world, config)
    _, drafts_b = step(world, config)

    assert drafts_a == drafts_b
