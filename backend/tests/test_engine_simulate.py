from app.engine.simulate import run_full, simulate
from app.schemas.experiment import ExperimentConfig


def test_simulate_returns_same_drafts_as_run_full():
    config = ExperimentConfig(seed=7, node_count=30)
    _, drafts_from_simulate = simulate(config)
    drafts_from_run_full = run_full(config)
    assert [d.event_type for d in drafts_from_simulate] == [
        d.event_type for d in drafts_from_run_full
    ]


def test_simulate_final_state_is_deterministic():
    config = ExperimentConfig(seed=7, node_count=30)
    state1, _ = simulate(config)
    state2, _ = simulate(config)
    assert {n: s.security_state for n, s in state1.nodes.items()} == {
        n: s.security_state for n, s in state2.nodes.items()
    }
    assert state1.tick == state2.tick


def test_simulate_final_state_matches_terminal_draft_counts():
    config = ExperimentConfig(seed=7, node_count=30)
    state, drafts = simulate(config)
    compromised_ids = {
        d.target_agent_id
        for d in drafts
        if d.event_type.value == "COMPROMISE_SUCCEEDED"
        and not d.metadata.get("already_compromised")
    }
    quarantined_ids = {d.agent_id for d in drafts if d.event_type.value == "AGENT_QUARANTINED"}
    for node_id, node in state.nodes.items():
        if node.security_state.value == "compromised":
            assert node_id in compromised_ids
        if node.security_state.value == "quarantined":
            assert node_id in quarantined_ids
