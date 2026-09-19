from app.engine.state import AgentNode, SecurityState, WorldState
from app.remediation.analyze import recommend
from app.schemas.experiment import ExperimentConfig
from app.security import detection


def test_no_recommendation_when_compromise_fraction_is_low():
    config = ExperimentConfig(seed=1, node_count=25, defense_enabled=True)
    assert recommend(config, compromise_fraction=0.1) == []


def test_no_recommendation_exactly_at_threshold():
    config = ExperimentConfig(seed=1, node_count=25)
    assert recommend(config, compromise_fraction=0.3) == []


def test_recommends_enabling_defense_when_disabled_and_compromise_is_high():
    config = ExperimentConfig(seed=1, node_count=25, defense_enabled=False)
    recs = recommend(config, compromise_fraction=0.5)
    assert len(recs) == 1
    assert recs[0].config_diff == {"defense_enabled": True}


def test_recommends_raising_detector_sensitivity_when_defense_enabled_but_insufficient():
    config = ExperimentConfig(
        seed=1, node_count=25, defense_enabled=True, detector_sensitivity=0.2
    )
    recs = recommend(config, compromise_fraction=0.5)
    assert len(recs) == 1
    assert recs[0].config_diff == {"detector_sensitivity": 0.4}


def test_sensitivity_recommendation_is_capped_at_one():
    config = ExperimentConfig(
        seed=1, node_count=25, defense_enabled=True, detector_sensitivity=0.9
    )
    recs = recommend(config, compromise_fraction=0.5)
    assert recs[0].config_diff == {"detector_sensitivity": 1.0}


def test_no_recommendation_when_sensitivity_already_maxed():
    config = ExperimentConfig(
        seed=1, node_count=25, defense_enabled=True, detector_sensitivity=1.0
    )
    assert recommend(config, compromise_fraction=0.9) == []


def test_no_sentinel_recommendation_when_plane_integrity_is_intact():
    config = ExperimentConfig(seed=1, node_count=25, sentinel_count=1)
    recs = recommend(config, compromise_fraction=0.9, security_plane_integrity=1.0)
    assert "sentinel_count" not in (recs[0].config_diff if recs else {})


def test_no_sentinel_recommendation_when_there_are_no_sentinels_to_add_to():
    config = ExperimentConfig(seed=1, node_count=25, sentinel_count=0)
    assert recommend(config, compromise_fraction=0.0, security_plane_integrity=0.0) == []


def test_recommends_raising_sentinel_count_when_plane_integrity_degrades():
    config = ExperimentConfig(seed=1, node_count=25, sentinel_count=1)
    recs = recommend(config, compromise_fraction=0.0, security_plane_integrity=0.5)
    assert len(recs) == 1
    assert recs[0].config_diff == {"sentinel_count": 2}


def test_sentinel_recommendation_is_capped_at_five():
    config = ExperimentConfig(seed=1, node_count=25, sentinel_count=5)
    assert recommend(config, compromise_fraction=0.0, security_plane_integrity=0.5) == []


def test_sentinel_recommendation_takes_priority_over_the_compromise_fraction_rules():
    config = ExperimentConfig(seed=1, node_count=25, sentinel_count=1, defense_enabled=False)
    recs = recommend(config, compromise_fraction=0.9, security_plane_integrity=0.5)
    assert recs[0].config_diff == {"sentinel_count": 2}


def _compromised_world(count: int) -> WorldState:
    ids = [f"agent-{i:03d}" for i in range(count)]
    nodes = {
        agent_id: AgentNode(
            id=agent_id,
            software_type="sw-a",
            security_state=SecurityState.COMPROMISED,
            neighbors=(),
            tick_compromised=0,
        )
        for agent_id in ids
    }
    return WorldState(tick=1, nodes=nodes, edges=())


def test_applying_the_sentinel_recommendation_measurably_increases_detected_anomalies():
    # The re-test loop (docs/PLAN.md §7): apply config_diff to a fresh
    # experiment and confirm the fix actually improves the situation the
    # recommendation targets -- here, more agents surviving a single
    # subverted sentinel's detection suppression.
    world = _compromised_world(10)
    baseline_config = ExperimentConfig(
        seed=1, node_count=25, sentinel_count=1, defense_enabled=True, detector_sensitivity=1.0
    )
    baseline_world = WorldState(
        tick=world.tick,
        nodes=world.nodes,
        edges=world.edges,
        compromised_graph_nodes=frozenset({"sentinel-000"}),
    )

    recs = recommend(baseline_config, compromise_fraction=1.0, security_plane_integrity=0.5)
    assert recs and recs[0].config_diff == {"sentinel_count": 2}

    fixed_config = baseline_config.model_copy(update=recs[0].config_diff)
    fixed_world = WorldState(
        tick=world.tick,
        nodes=world.nodes,
        edges=world.edges,
        compromised_graph_nodes=frozenset({"sentinel-000"}),
    )

    _, baseline_drafts = detection.step(baseline_world, baseline_config)
    _, fixed_drafts = detection.step(fixed_world, fixed_config)

    baseline_detected = {
        d.agent_id for d in baseline_drafts if d.event_type.value == "ANOMALY_DETECTED"
    }
    fixed_detected = {d.agent_id for d in fixed_drafts if d.event_type.value == "ANOMALY_DETECTED"}
    assert len(fixed_detected) > len(baseline_detected)
