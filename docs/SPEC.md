# AgentShield — Milestone 0 Specification

> **Scope:** the §4 vertical slice only. This document is subordinate to `docs/BRIEF.md`; where they conflict, the brief wins on intent and this document wins on mechanism.
>
> **Status:** all six §13 open decisions are resolved below (§1), plus one adjacent transport choice. No decision here may be changed silently — amend §1 and note the date.
>
> **Pivot notice:** this document specifies the M0 vertical slice mechanism (event schema,
> RNG, engine clock, snapshot/delta protocol). That mechanism is preserved unchanged under the
> product's evolution into a Multi-Agent Adversarial Resilience Platform — see `docs/PLAN.md`
> for the current authoritative architecture (typed security graph, pluggable attack scenarios,
> adaptive attacker, remediation) that builds on top of it.

---

## 1. Resolved decisions

| §13 | Decision | Resolution |
|---|---|---|
| 1a | Event identity & ordering | `seq: int` (monotonic per experiment) is the **sole ordering key**. `event_id: UUID4` is global identity. Time splits into `sim_tick: int` (engine truth) and `wall_time: datetime` (display only). |
| 1b | Schema versioning | `schema_version: int`, currently `1`, from one frozen constant. Within a version, only **optional additive** fields. Any breaking change bumps the int and adds an explicit upcaster. Readers reject unknown versions loudly. |
| 2 | Simulation clock | **Fixed-tick, synchronous core.** `step()` is pure: `(state, config) → (state', event drafts)`. No `async`, no `sleep`, no I/O inside it. An async driver owns wall-clock pacing. |
| 3 | Determinism | **Derived keyed RNG.** No long-lived RNG state. Every draw calls `rng(seed, tick, agent_id, purpose)`, which hashes the key into a fresh generator. Order-independent by construction. |
| 4 | Pydantic ↔ TypeScript | **Generated from OpenAPI.** Pydantic is source of truth; `openapi-typescript` emits a committed `schema.d.ts`; CI fails on drift. WS frames enter OpenAPI via a real `GET /api/schema/events` endpoint. |
| 5 | Snapshot vs deltas | **Snapshot then deltas.** One `snapshot` frame on connect, then `event` frames. Reconnect via `?since_seq=N`. Client applies both through one reducer, which Phase 1.5 replay reuses. |
| 6 | Postgres in M0 | **In Compose, unused by application code.** Container runs with a healthcheck from day one; the M0 simulation is fully in-memory and writes nothing. |
| — | Stream transport | **WebSocket** (`WS /api/experiments/{id}/stream`), so M1 controls can travel over the same connection. |

### Deliberate deviations from the brief

§5 lists a single `timestamp` field. This spec splits it into `sim_tick` and `wall_time`, because §9.4 requires simulation time to be independent of wall-clock time and replay ordering must not depend on a clock. The §5 `id` field becomes the pair `event_id` + `seq` per decision 1a. These are the only shape changes; every other §5 field is preserved by name.

---

## 2. Repository layout

Files marked **(M0)** are created in this milestone. The rest are named for orientation and are not built yet.

```
agentnet/
├── docker-compose.yml                        (M0)
├── Makefile                                  (M0)
├── README.md                                 (M0 — update)
├── .github/workflows/ci.yml                  (M0)
├── docs/
│   ├── BRIEF.md
│   └── SPEC.md
├── backend/
│   ├── Dockerfile                            (M0)
│   ├── pyproject.toml                        (M0)
│   ├── app/
│   │   ├── main.py                           (M0)  FastAPI app + router wiring
│   │   ├── config.py                         (M0)  Settings (pydantic-settings)
│   │   ├── schemas/
│   │   │   ├── events.py                     (M0)  EventType, EventDraft, Event
│   │   │   ├── frames.py                     (M0)  SnapshotFrame, EventFrame, StreamFrame
│   │   │   └── experiment.py                 (M0)  ExperimentConfig, ExperimentSummary, NodeView, EdgeView
│   │   ├── engine/
│   │   │   ├── rng.py                        (M0)  derived keyed RNG
│   │   │   ├── state.py                      (M0)  SecurityState, AgentNode, WorldState
│   │   │   ├── topology.py                   (M0)  build_world()
│   │   │   └── propagation.py                (M0)  step()
│   │   ├── events/
│   │   │   ├── version.py                    (M0)  SCHEMA_VERSION
│   │   │   ├── emitter.py                    (M0)  EventEmitter — assigns seq / uuid / wall_time
│   │   │   ├── bus.py                        (M0)  EventBus — fan-out + ring buffer
│   │   │   └── migrations.py                 (later — does not exist until v2 does)
│   │   ├── orchestrator/
│   │   │   ├── runner.py                     (M0)  ExperimentRunner — the async driver
│   │   │   └── registry.py                   (M0)  in-memory experiment registry
│   │   └── api/
│   │       ├── routes_experiments.py         (M0)
│   │       ├── routes_schema.py              (M0)
│   │       └── ws.py                         (M0)
│   └── tests/
│       ├── test_rng.py                       (M0)
│       ├── test_determinism.py               (M0)
│       ├── test_event_schema.py              (M0)
│       └── test_stream.py                    (M0)
└── frontend/
    ├── Dockerfile                            (M0)
    ├── package.json                          (M0)
    └── src/
        ├── app/page.tsx                      (M0)  dashboard shell
        ├── components/
        │   ├── NetworkGraph.tsx              (M0)  Sigma.js + Graphology hero visual
        │   └── EventStream.tsx               (M0)  bottom log
        └── lib/
            ├── api/schema.d.ts               (M0 — GENERATED, committed)
            ├── api/client.ts                 (M0)
            └── stream/
                ├── reducer.ts                (M0)  reduce(state, frame) → state
                └── useExperimentStream.ts    (M0)  WS hook + reconnect
```

---

## 3. Backend interfaces

### 3.1 `app/engine/rng.py`

```python
def rng(seed: int, tick: int, agent_id: str, purpose: str) -> random.Random:
    """Deterministic generator for one (tick, agent, purpose) draw site.

    The key fully determines the stream, so results never depend on the order
    in which draws happen. Never cache or reuse the returned object.
    """
```

Implemented with `hashlib.blake2b` over `f"{seed}|{tick}|{agent_id}|{purpose}"`. **No other source of randomness is permitted anywhere under `app/engine/` or `app/orchestrator/`** — no bare `random.`, no `numpy.random`, no `uuid4()` inside `step()`.

### 3.2 `app/engine/state.py`

```python
class SecurityState(StrEnum):
    HEALTHY, SUSPICIOUS, COMPROMISED, QUARANTINED, RECOVERED

@dataclass
class AgentNode:
    id: str                       # "agent-000", zero-padded so it sorts lexicographically
    software_type: str            # "sw-a" | "sw-b" | "sw-c"
    security_state: SecurityState
    neighbors: tuple[str, ...]
    compromised_by: str | None = None
    tick_compromised: int | None = None

@dataclass
class WorldState:
    tick: int
    nodes: dict[str, AgentNode]   # insertion order == sorted id order
    edges: tuple[tuple[str, str], ...]
```

M0 uses only `HEALTHY` and `COMPROMISED`. The other three members exist and stay unused — per §3 of the brief, security state is never scattered booleans.

### 3.3 `app/engine/topology.py`

```python
def build_world(config: ExperimentConfig) -> tuple[WorldState, list[EventDraft]]:
    """Build topology, assign software types, seed the initial compromise.

    Returns tick-0 state plus one AGENT_CREATED draft per node and one
    COMPROMISE_SUCCEEDED draft for the seeded node.
    """
```

Topology is `networkx.barabasi_albert_graph(n=config.node_count, m=config.edge_density, seed=config.seed)`. Software types are assigned round-robin over sorted node IDs — deterministic, and it makes the diversity mix controllable later. The seeded initial compromise defaults to the highest-degree node, ties broken by lowest ID.

### 3.4 `app/engine/propagation.py`

```python
def step(state: WorldState, config: ExperimentConfig) -> tuple[WorldState, list[EventDraft]]:
    """Advance exactly one tick. Pure, synchronous, total.

    Same (state, config) in → same (state', drafts) out, always.
    """
```

The rule, executed against a frozen snapshot of tick-N state so that within-tick ordering cannot matter:

1. Sources = nodes whose `security_state is COMPROMISED`, iterated in sorted ID order.
2. For each source, targets = its `HEALTHY` neighbors, in sorted ID order.
3. `p = config.p_same if same software_type else config.p_cross`.
4. Draw `rng(config.seed, state.tick, target_id, f"infect:{source_id}").random() < p`.
5. Emit `COMPROMISE_ATTEMPTED`, then `COMPROMISE_SUCCEEDED` or `COMPROMISE_FAILED`.
6. If several sources hit one target in the same tick, **all** attempts are emitted, but the first success in sorted source order sets `compromised_by`. Later successes against an already-claimed target carry `metadata.already_compromised = true`.
7. Newly compromised nodes become sources only from tick N+1.

`p_same > p_cross` is a **simulation parameter, not a finding** (§4). Every propagation event sets `metadata.probability`, so any number that ends up on screen is traceable to the input that produced it.

The run ends when `config.max_ticks` is reached, or when no `HEALTHY` node borders a `COMPROMISED` one.

### 3.5 `app/schemas/events.py`

```python
class EventType(StrEnum):
    ...   # the complete §5 list is declared here

class EventDraft(BaseModel):
    """Engine output: no identity, no clock. This is what keeps step() pure."""
    sim_tick: int
    event_type: EventType
    agent_id: str | None = None
    source_agent_id: str | None = None
    target_agent_id: str | None = None
    risk_score: float | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

class Event(EventDraft):
    """Emitted, ordered, streamable."""
    event_id: UUID
    seq: int
    schema_version: int = SCHEMA_VERSION
    experiment_id: UUID
    wall_time: datetime
```

The full `EventType` enum is declared now; M0 emits only `EXPERIMENT_STARTED`, `EXPERIMENT_STOPPED`, `AGENT_CREATED`, `COMPROMISE_ATTEMPTED`, `COMPROMISE_SUCCEEDED`, `COMPROMISE_FAILED`. There is deliberately no `AGENT_STATE_CHANGED` type: `COMPROMISE_SUCCEEDED` **is** the `HEALTHY → COMPROMISED` transition, and the frontend reducer derives node state from it.

### 3.6 `app/events/emitter.py`, `app/events/bus.py`

```python
class EventEmitter:
    """Sole assigner of seq. One instance per experiment."""
    def emit(self, drafts: Sequence[EventDraft]) -> list[Event]: ...

class EventBus:
    """Fan-out to live subscribers, plus a bounded replay buffer."""
    RING_SIZE = 2000
    async def publish(self, events: Sequence[Event]) -> None: ...
    def subscribe(self) -> AsyncIterator[Event]: ...
    def since(self, seq: int) -> list[Event] | None:   # None = outside the buffer
```

`seq` starts at 0 and increments by exactly one per event, with no gaps — the client treats a gap as a fatal desync and reconnects. `event_id` and `wall_time` are assigned here rather than in the engine, which is what keeps `step()` pure and why those two fields are excluded from determinism comparison (§6.1).

Phase 1.5 adds a `PostgresWriter` as a second bus subscriber. Nothing else changes.

### 3.7 `app/orchestrator/runner.py`

```python
class ExperimentRunner:
    """The only place wall-clock time exists."""
    async def run(self) -> None:
        while self._running and not self._finished():
            self.state, drafts = step(self.state, self.config)
            await self.bus.publish(self.emitter.emit(drafts))
            await asyncio.sleep(self.tick_interval)

    def snapshot(self) -> SnapshotFrame: ...
```

`tick_interval` is a constant (`0.25s`) in M0. Pause, resume, reset, and speed are **not built** — the clock decision makes them additive in M1 (stop calling `step()`; divide the interval), and no M0 code should anticipate them.

### 3.8 HTTP + WebSocket surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness. Reports Postgres reachability without otherwise using it. |
| `POST` | `/api/experiments` | Body `ExperimentConfig`; creates, starts, returns `ExperimentSummary`. |
| `GET` | `/api/experiments/{id}` | `ExperimentSummary`. |
| `POST` | `/api/experiments/{id}/stop` | Halts the driver, emits `EXPERIMENT_STOPPED`. |
| `GET` | `/api/schema/events` | Returns the `StreamFrame` union — the typegen anchor that pulls WS payloads into OpenAPI. |
| `WS` | `/api/experiments/{id}/stream?since_seq=N` | Live stream. |

```python
class ExperimentConfig(BaseModel):
    seed: int
    node_count: int = Field(60, ge=25, le=100)     # §4 bound
    edge_density: int = Field(2, ge=1, le=5)       # Barabási–Albert "m"
    software_type_count: int = Field(3, ge=1, le=5)
    p_same: float = Field(0.15, ge=0.0, le=1.0)
    p_cross: float = Field(0.03, ge=0.0, le=1.0)
    max_ticks: int = Field(200, ge=1, le=2000)
```

Stream protocol:

```
client connects (optionally ?since_seq=N)
  ├── since_seq absent, or outside the ring buffer
  │     └── server sends SnapshotFrame{last_seq}, then EventFrames from last_seq+1
  └── since_seq inside the buffer
        └── server sends EventFrames from N+1, no snapshot
```

```python
class SnapshotFrame(BaseModel):
    type: Literal["snapshot"]
    experiment_id: UUID
    last_seq: int
    sim_tick: int
    status: Literal["running", "finished", "stopped"]
    nodes: list[NodeView]     # id, software_type, security_state
    edges: list[EdgeView]     # source, target

class EventFrame(BaseModel):
    type: Literal["event"]
    event: Event

StreamFrame = Annotated[SnapshotFrame | EventFrame, Field(discriminator="type")]
```

---

## 4. Frontend interfaces

**`src/lib/stream/reducer.ts`** — the shared code path that decision 5 buys us:

```ts
export type GraphState = {
  experimentId: string | null;
  lastSeq: number;
  tick: number;
  nodes: Map<string, NodeView>;
  edges: EdgeView[];
  recentEvents: Event[];        // capped at 200 for the bottom panel
};

export function reduce(state: GraphState, frame: StreamFrame): GraphState;
```

`reduce` is pure and has no React or DOM dependency, so Phase 1.5 replay can drive it from a stored log with zero changes. `COMPROMISE_SUCCEEDED` sets the target's `security_state` to `COMPROMISED`. An unrecognized `event_type` is appended to `recentEvents` and otherwise ignored — that is what makes §1b's additive rule safe. An unrecognized `schema_version` is a hard error surfaced in the UI, never a silent skip.

**`src/lib/stream/useExperimentStream.ts`** — owns the socket: connects, feeds frames to `reduce`, reconnects with exponential backoff (250 ms → 5 s) passing `since_seq=lastSeq`, and treats a `seq` gap as a desync requiring a fresh snapshot.

**`src/components/NetworkGraph.tsx`** — Sigma.js over a Graphology instance built once from the snapshot. Events call `graph.setNodeAttribute(id, "color", …)` rather than rebuilding the graph. Per §7, **not React Flow**. Layout is `graphology-layout-forceatlas2`, run for a fixed iteration count at snapshot time so node positions are stable across reruns of the same seed.

State colors are defined once in `NetworkGraph.tsx` and are the only place state maps to appearance: healthy = slate, suspicious = amber, compromised = red, quarantined = blue, recovered = green.

**Type generation** — `make types` runs `openapi-typescript http://localhost:8000/openapi.json -o frontend/src/lib/api/schema.d.ts`. The output is committed. CI regenerates it and runs `git diff --exit-code`; drift fails the build.

---

## 5. Explicitly out of scope for Milestone 0

Building any of these is scope creep, not initiative.

- **Persistence of anything.** Postgres runs in Compose and is untouched by application code. No ORM, no migrations, no `events` table.
- **Quarantine, detection, risk scoring, the Security Engine.** `risk_score` exists on the event model and stays `None`.
- **The metrics panel.** No counts, no rates, no `R_eff`.
- **The agent detail panel.** Clicking a node does nothing.
- **Start / Pause / Reset / Speed controls**, and any backend endpoint serving them.
- **Configuration UI.** Config arrives as a `POST` body; the left rail is a static summary of the running experiment.
- **Replay UI.** Architectural affordance only — a pure reducer and a gapless ordered log.
- **LLMs, Model Gateway, agent runtime, tools, memory, credentials, sandboxing.**
- **Comparison mode, experiment sweeps, event-log export.**
- **Auth, multi-tenancy, multi-user concurrency.** One experiment at a time is acceptable; the registry is a dict.

---

## 6. Verification

### 6.1 Automated

`make test` runs `pytest` plus the type-drift check. Required tests:

| File | Asserts |
|---|---|
| `test_rng.py` | Same key → same value; different keys → different streams; results independent of call order. |
| `test_determinism.py` | Two full runs at `seed=42` produce **identical event sequences**, comparing `(seq, sim_tick, event_type, agent_id, source_agent_id, target_agent_id, metadata)`. `event_id` and `wall_time` are excluded by design — they are identity and display, not simulation output. A third run at `seed=43` must differ. |
| `test_event_schema.py` | Every emitted event has `schema_version == 1`; `seq` is gapless from 0; only the six M0 event types appear. |
| `test_stream.py` | A fresh client gets `snapshot` then `event` frames; a client reconnecting with `since_seq=N` inside the buffer gets no snapshot and resumes at `N+1`; outside the buffer it gets a fresh snapshot. |

### 6.2 End-to-end acceptance

The milestone is done when this sequence passes on a clean checkout. Commands are PowerShell-safe (`curl.exe`, not the `curl` alias).

```powershell
# 1. One command starts everything — no manual Postgres setup (§7).
docker compose up --build

# 2. Backend and database are up.
curl.exe -s http://localhost:8000/health
#    → {"status":"ok","postgres":"reachable"}

# 3. Start a seeded experiment.
curl.exe -s -X POST http://localhost:8000/api/experiments `
  -H "Content-Type: application/json" `
  -d '{\"seed\":42,\"node_count\":60}'
#    → {"experiment_id":"…","status":"running", …}

# 4. Open http://localhost:3000
```

Observe, in the browser:

1. The graph renders **60 nodes** with visible edges within ~2 seconds.
2. Exactly **one node is red** at tick 0; the rest are slate.
3. Over the following ticks, red spreads **only along edges**, and same-software neighbors visibly fall faster than cross-software ones.
4. The bottom event stream fills with `COMPROMISE_ATTEMPTED` / `_SUCCEEDED` / `_FAILED` rows carrying monotonic `seq` values with no gaps.
5. A node's recolor and its corresponding event row appear together — the graph is rendering the event log, not running a parallel client-side simulation.

Then:

```powershell
# 5. Determinism, end to end: rerun the same seed and diff the logs.
make verify-determinism
#    Runs seed 42 twice headless, writes both event logs to
#    ./.artifacts/run-{1,2}.jsonl, diffs the deterministic projection.
#    → "PASS: 1284 events identical"

# 6. Contract drift.
make types
git diff --exit-code frontend/src/lib/api/schema.d.ts
#    → no output, exit 0

# 7. Reconnect. With the experiment still running, bounce the backend.
docker compose restart backend
```

On reconnect, the graph must resume with node states intact and the event stream must continue from the next `seq` — no gap, no replayed duplicates. This is the single check that proves decision 5 works and that Phase 1.5 replay will share the live code path.

**Milestone 0 is complete when steps 1–7 pass and nothing listed in §5 has been built.**
