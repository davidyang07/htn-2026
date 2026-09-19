import pytest

from app.engine.replay import ReplayUnsupportedError, reconstruct_final_state
from app.engine.tick import advance
from app.engine.topology import build_world
from app.schemas.experiment import ExperimentConfig


def test_reconstruct_final_state_matches_manual_advance_to_the_same_tick():
    config = ExperimentConfig(seed=7, node_count=30, p_same=0.3, max_ticks=10)
    world, _ = build_world(config)
    for _ in range(4):
        world, _ = advance(world, config)

    reconstructed, _ = reconstruct_final_state(config, target_tick=4)

    assert reconstructed.tick == world.tick == 4
    assert {n: s.security_state for n, s in reconstructed.nodes.items()} == {
        n: s.security_state for n, s in world.nodes.items()
    }


def test_reconstruct_final_state_stops_at_target_tick_even_if_not_yet_finished():
    config = ExperimentConfig(seed=7, node_count=30, p_same=0.3, max_ticks=200)
    reconstructed, _ = reconstruct_final_state(config, target_tick=2)
    assert reconstructed.tick == 2


def test_reconstruct_final_state_is_deterministic():
    config = ExperimentConfig(seed=11, node_count=25, p_same=0.2, max_ticks=50)
    world1, events1 = reconstruct_final_state(config, target_tick=8)
    world2, events2 = reconstruct_final_state(config, target_tick=8)
    assert {n: s.security_state for n, s in world1.nodes.items()} == {
        n: s.security_state for n, s in world2.nodes.items()
    }
    assert [e.event_type for e in events1] == [e.event_type for e in events2]


def test_reconstruct_final_state_returns_events_with_matching_experiment_id():
    config = ExperimentConfig(seed=3, node_count=25, max_ticks=3)
    _, events = reconstruct_final_state(config, target_tick=2)
    ids = {e.experiment_id for e in events}
    assert len(ids) == 1


def test_reconstruct_final_state_rejects_real_provider():
    config = ExperimentConfig(
        seed=1, node_count=25, real_agent_count=2, model_provider="vllm", max_ticks=3
    )
    with pytest.raises(ReplayUnsupportedError):
        reconstruct_final_state(config, target_tick=2)


def test_reconstruct_final_state_supports_mock_provider_with_real_agents():
    config = ExperimentConfig(
        seed=5,
        node_count=25,
        real_agent_count=3,
        model_provider="mock",
        active_scenarios=["propagation", "prompt_injection"],
        max_ticks=4,
    )
    world, events = reconstruct_final_state(config, target_tick=3)
    assert world.tick == 3
    assert events
