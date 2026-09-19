import networkx as nx

from app.engine.rng import rng
from app.engine.state import AgentNode, SecurityState, WorldState
from app.schemas.events import EventDraft, EventType
from app.schemas.experiment import ExperimentConfig

_TYPE_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def _software_types(sorted_ids: list[str], software_type_count: int) -> dict[str, str]:
    labels = [f"sw-{_TYPE_LETTERS[i]}" for i in range(software_type_count)]
    return {node_id: labels[i % software_type_count] for i, node_id in enumerate(sorted_ids)}


def _generate_confidential_token(seed: int, node_id: str) -> str:
    """Deterministic per-(seed, node_id) synthetic secret (docs/PHASE_2_PLAN.md
    §4/§6) -- reproducible across replays of the same seed, never derived
    from anything real. Uses the same rng() keying discipline as every other
    engine draw site, drawing raw bytes rather than a float."""
    draw = rng(seed, 0, node_id, "confidential_token")
    return f"TOKEN-{draw.getrandbits(64):016x}"


def _select_real_agents(sorted_ids: list[str], degree: dict[str, int], count: int) -> set[str]:
    """The `count` highest-degree nodes become agent_kind="real" (ties broken
    by lowest id -- same convention build_world() already uses for
    initial_compromised="highest_degree"). Barabasi-Albert graphs are hub-
    heavy, so highest-degree selection maximizes the odds that at least one
    real-real edge exists for the LLM-mediated propagation path to exercise,
    rather than leaving that to chance (docs/PHASE_2_PLAN.md §4)."""
    if count <= 0:
        return set()
    ranked = sorted(sorted_ids, key=lambda n: (-degree[n], n))
    return set(ranked[:count])


def build_world_from_agents(
    agent_ids: list[str], edges: set[tuple[str, str]], config: ExperimentConfig
) -> tuple[WorldState, list[EventDraft]]:
    """Same assembly as build_world (software-type round-robin, seeded
    initial compromise, real-agent selection, confidential tokens) but over
    a caller-supplied topology instead of a barabasi_albert_graph draw --
    the entry point for importing an externally-authored multi-agent
    topology (app/importers/external_topology.py). Agent ids are
    caller-defined strings (not the "agent-NNN" convention build_world
    generates), sorted for every deterministic operation exactly like
    build_world sorts its generated ids.
    """
    sorted_ids = sorted(agent_ids)
    types = _software_types(sorted_ids, config.software_type_count)

    neighbors: dict[str, set[str]] = {n: set() for n in sorted_ids}
    edge_set: set[tuple[str, str]] = set()
    for u, v in edges:
        neighbors[u].add(v)
        neighbors[v].add(u)
        edge_set.add((u, v) if u < v else (v, u))

    degree = {n: len(neighbors[n]) for n in sorted_ids}

    if config.initial_compromised == "random_node":
        seed_node = rng(config.seed, 0, "topology", "initial_compromise").choice(sorted_ids)
    else:
        max_degree = max(degree.values())
        seed_node = sorted(n for n in sorted_ids if degree[n] == max_degree)[0]

    real_agent_ids = _select_real_agents(sorted_ids, degree, config.real_agent_count)

    nodes: dict[str, AgentNode] = {}
    for n in sorted_ids:
        state = SecurityState.COMPROMISED if n == seed_node else SecurityState.HEALTHY
        is_real = n in real_agent_ids
        nodes[n] = AgentNode(
            id=n,
            software_type=types[n],
            security_state=state,
            neighbors=tuple(sorted(neighbors[n])),
            compromised_by=None,
            tick_compromised=0 if n == seed_node else None,
            agent_kind="real" if is_real else "simulated",
            confidential_token=_generate_confidential_token(config.seed, n) if is_real else None,
        )

    world = WorldState(tick=0, nodes=nodes, edges=tuple(sorted(edge_set)))

    drafts: list[EventDraft] = []
    for n in sorted_ids:
        drafts.append(
            EventDraft(
                sim_tick=0,
                event_type=EventType.AGENT_CREATED,
                agent_id=n,
                metadata={"software_type": types[n]},
            )
        )
    drafts.append(
        EventDraft(
            sim_tick=0,
            event_type=EventType.COMPROMISE_SUCCEEDED,
            target_agent_id=seed_node,
            metadata={"initial_compromise": True},
        )
    )

    return world, drafts


def build_world(config: ExperimentConfig) -> tuple[WorldState, list[EventDraft]]:
    """Build topology, assign software types, seed the initial compromise.

    Returns tick-0 state plus one AGENT_CREATED draft per node and one
    COMPROMISE_SUCCEEDED draft for the seeded node.
    """
    graph = nx.barabasi_albert_graph(
        n=config.node_count, m=config.edge_density, seed=config.seed
    )

    def node_id(i: int) -> str:
        return f"agent-{i:03d}"

    sorted_ids = sorted(node_id(i) for i in graph.nodes)
    edge_set = {
        (node_id(u), node_id(v)) if node_id(u) < node_id(v) else (node_id(v), node_id(u))
        for u, v in graph.edges
    }
    return build_world_from_agents(sorted_ids, edge_set, config)
