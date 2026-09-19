import asyncio

from app.agents.runtime import real_agent_step
from app.engine.state import AgentNode, SecurityState, WorldState
from app.gateway.gateway import ModelGateway
from app.gateway.mock_provider import MockProvider
from app.gateway.schemas import ModelRequest, ModelResponse
from app.schemas.experiment import ExperimentConfig


def _real_node(node_id, state, neighbors, token="TOKEN-fixed", software_type="sw-a") -> AgentNode:
    return AgentNode(
        id=node_id,
        software_type=software_type,
        security_state=state,
        neighbors=neighbors,
        agent_kind="real",
        confidential_token=token,
    )


def _gateway(provider=None, **overrides) -> ModelGateway:
    defaults = dict(
        timeout_s=5.0, max_retries=1, max_concurrency=8, max_requests_per_experiment=1000
    )
    defaults.update(overrides)
    return ModelGateway(provider or MockProvider(), **defaults)


def _config(**overrides) -> ExperimentConfig:
    defaults = dict(seed=42, node_count=25, p_same=1.0, p_cross=1.0)
    defaults.update(overrides)
    return ExperimentConfig(**defaults)


def test_no_compromised_real_agents_returns_unchanged_state_and_no_drafts():
    nodes = {
        "agent-000": _real_node("agent-000", SecurityState.HEALTHY, ("agent-001",)),
        "agent-001": _real_node("agent-001", SecurityState.HEALTHY, ("agent-000",)),
    }
    world = WorldState(tick=1, nodes=nodes, edges=(("agent-000", "agent-001"),))

    new_world, drafts = asyncio.run(real_agent_step(world, _config(), _gateway(), tick=1))

    assert drafts == []
    assert new_world is world


def test_leak_emits_model_and_tool_events_then_compromise_succeeded():
    nodes = {
        "agent-000": _real_node("agent-000", SecurityState.COMPROMISED, ("agent-001",)),
        "agent-001": _real_node("agent-001", SecurityState.HEALTHY, ("agent-000",)),
    }
    world = WorldState(tick=1, nodes=nodes, edges=(("agent-000", "agent-001"),))
    # p_same=1.0 -> mock_leak_probability=1.0 -> MockProvider always leaks.
    config = _config(p_same=1.0)

    new_world, drafts = asyncio.run(real_agent_step(world, config, _gateway(), tick=1))

    event_types = [d.event_type.value for d in drafts]
    assert event_types == [
        "MODEL_REQUESTED",
        "MODEL_RESPONDED",
        "COMPROMISE_ATTEMPTED",
        "TOOL_EXECUTED",
        "COMPROMISE_SUCCEEDED",
    ]
    assert new_world.nodes["agent-001"].security_state == SecurityState.COMPROMISED
    assert new_world.nodes["agent-001"].compromised_by == "agent-000"
    assert new_world.nodes["agent-001"].tick_compromised == 1
    # source untouched, only target replaced
    assert new_world.nodes["agent-000"] is world.nodes["agent-000"]


def test_no_leak_emits_compromise_failed_no_tool_event():
    nodes = {
        "agent-000": _real_node("agent-000", SecurityState.COMPROMISED, ("agent-001",)),
        "agent-001": _real_node("agent-001", SecurityState.HEALTHY, ("agent-000",)),
    }
    world = WorldState(tick=1, nodes=nodes, edges=(("agent-000", "agent-001"),))
    config = _config(p_same=0.0, p_cross=0.0)

    new_world, drafts = asyncio.run(real_agent_step(world, config, _gateway(), tick=1))

    event_types = [d.event_type.value for d in drafts]
    assert event_types == [
        "MODEL_REQUESTED",
        "MODEL_RESPONDED",
        "COMPROMISE_ATTEMPTED",
        "COMPROMISE_FAILED",
    ]
    assert new_world.nodes["agent-001"].security_state == SecurityState.HEALTHY


def test_gateway_error_short_circuits_to_compromise_failed_no_model_events():
    class _AlwaysNoneGateway:
        async def complete(self, request: ModelRequest) -> ModelResponse | None:
            return None

    nodes = {
        "agent-000": _real_node("agent-000", SecurityState.COMPROMISED, ("agent-001",)),
        "agent-001": _real_node("agent-001", SecurityState.HEALTHY, ("agent-000",)),
    }
    world = WorldState(tick=1, nodes=nodes, edges=(("agent-000", "agent-001"),))

    new_world, drafts = asyncio.run(
        real_agent_step(world, _config(), _AlwaysNoneGateway(), tick=1)
    )

    assert len(drafts) == 1
    assert drafts[0].event_type.value == "COMPROMISE_FAILED"
    assert drafts[0].metadata["gateway_error"] is True
    assert new_world.nodes["agent-001"].security_state == SecurityState.HEALTHY


def test_two_real_sources_claim_tie_break_matches_propagation_convention():
    nodes = {
        "agent-000": _real_node("agent-000", SecurityState.COMPROMISED, ("agent-002",)),
        "agent-001": _real_node("agent-001", SecurityState.COMPROMISED, ("agent-002",)),
        "agent-002": _real_node("agent-002", SecurityState.HEALTHY, ("agent-000", "agent-001")),
    }
    world = WorldState(
        tick=1, nodes=nodes, edges=(("agent-000", "agent-002"), ("agent-001", "agent-002"))
    )
    config = _config(p_same=1.0)

    new_world, drafts = asyncio.run(real_agent_step(world, config, _gateway(), tick=1))

    successes = [d for d in drafts if d.event_type.value == "COMPROMISE_SUCCEEDED"]
    assert len(successes) == 2
    # sorted source order: agent-000 wins the claim first.
    assert successes[0].source_agent_id == "agent-000"
    assert "already_compromised" not in successes[0].metadata
    assert successes[1].source_agent_id == "agent-001"
    assert successes[1].metadata["already_compromised"] is True
    assert new_world.nodes["agent-002"].compromised_by == "agent-000"


def test_real_simulated_neighbor_never_attempted_by_real_agent_step():
    """A real node's simulated neighbor is out of scope for this function --
    it's handled by the unchanged probabilistic propagation.step() path
    (docs/PHASE_2_PLAN.md §5)."""
    nodes = {
        "agent-000": _real_node("agent-000", SecurityState.COMPROMISED, ("agent-001",)),
        "agent-001": AgentNode(
            id="agent-001",
            software_type="sw-a",
            security_state=SecurityState.HEALTHY,
            neighbors=("agent-000",),
        ),
    }
    world = WorldState(tick=1, nodes=nodes, edges=(("agent-000", "agent-001"),))

    _, drafts = asyncio.run(real_agent_step(world, _config(), _gateway(), tick=1))
    assert drafts == []


def test_deterministic_across_repeated_runs_with_mock_provider():
    nodes = {
        "agent-000": _real_node(
            "agent-000", SecurityState.COMPROMISED, ("agent-001", "agent-002")
        ),
        "agent-001": _real_node(
            "agent-001", SecurityState.HEALTHY, ("agent-000",), token="TOKEN-x"
        ),
        "agent-002": _real_node(
            "agent-002", SecurityState.HEALTHY, ("agent-000",), token="TOKEN-y"
        ),
    }
    world = WorldState(
        tick=1, nodes=nodes, edges=(("agent-000", "agent-001"), ("agent-000", "agent-002"))
    )
    config = _config(p_same=0.5, p_cross=0.5)

    async def run_once():
        return await real_agent_step(world, config, _gateway(), tick=1)

    _, drafts_a = asyncio.run(run_once())
    _, drafts_b = asyncio.run(run_once())

    def project(drafts):
        return [
            (
                d.event_type.value,
                d.sim_tick,
                d.agent_id,
                d.source_agent_id,
                d.target_agent_id,
                d.metadata,
            )
            for d in drafts
        ]

    assert project(drafts_a) == project(drafts_b)
