# AgentShield — Architecture

> **Scope:** how the product in `docs/PROJECT.md` is built. Mechanism defined by `docs/SPEC.md`
> (event schema, derived-keyed RNG, fixed-tick engine, snapshot/delta protocol) is preserved and
> reused verbatim; where SPEC and this document disagree on mechanism, SPEC wins.
>
> **Reading order for a new coding agent:** `docs/PROJECT.md` → this file → `docs/MVP_PLAN.md`.

---

## 1. The whole picture

```
                                   USER
                                     |
                                     |  "Find and fix the authentication vulnerability
                                     |   in this repository, add regression coverage,
                                     |   and verify the patch."
                                     v
        +====================================================================+
        |                            WORKSWARM                               |
        |                  (openJiuwen; NOT modified by us)                  |
        |                                                                    |
        |                      WorkSwarm Leader                              |
        |                   (task decomposition)                             |
        |                            |                                       |
        |         +------------------+------------------+                    |
        |         |                                     |                    |
        |         v                                     v                    |
        |   Repo Analyst                        Security Researcher          |
        |         |                                     |                    |
        |         |                            reads repository docs         |
        |         |                                     |                    |
        |         |                          +----------v-----------+        |
        |         |                          |  POISONED DOC FILE   |        |
        |         |                          |  indirect prompt     |        |
        |         |                          |  injection           |        |
        |         |                          +----------+-----------+        |
        |         |                                     |                    |
        |         |                          worker emits STRUCTURED         |
        |         |                          resource request (it has        |
        |         |                          NO filesystem capability)       |
        +=========|=====================================|====================+
                  |                                     |
                  |  resource request                   |  resource request
                  |  (benign)                           |  demo_target/secrets/
                  |                                     |  demo_secret.txt
                  v                                     v
        +====================================================================+
        |                    AGENTSHIELD CONTROL PLANE                       |
        |                (external; deterministic; no LLM)                   |
        |                                                                    |
        |        POST /api/runtime/sessions/{id}/resource-request             |
        |                            |                                       |
        |                            v                                       |
        |                  +--------------------+                            |
        |                  | DETERMINISTIC      |                            |
        |                  | POLICY             |                            |
        |                  | deny  demo_target/ |                            |
        |                  |       secrets/**   |                            |
        |                  +----+----------+----+                            |
        |                       |          |                                 |
        |                 ALLOW |          | DENY                            |
        |                       |          |                                 |
        |                       |          +--> POLICY_VIOLATION             |
        |                       |          +--> TOOL_DENIED                  |
        |                       |          +--> ANOMALY_DETECTED             |
        |                       |          +--> AGENT_QUARANTINED            |
        |                       |          +--> taint worker's artifacts     |
        |                       |          +--> recovery_required = true     |
        |                       |                                            |
        |     every decision -> EventEmitter -> EventBus -> WebSocket -> UI   |
        +=======================|==========================|=================+
                                |                          |
                   allow: worker continues     deny + "recovery required"
                                |                          |
                                |                          v
        +=======================|==========================|=================+
        |                       |      WORKSWARM (cont.)   |                 |
        |                       |                          v                 |
        |                       |         +--------------------------+       |
        |                       |         | Replacement Researcher   |       |
        |                       |         | seeded with TRUSTED      |       |
        |                       |         | context only -- the      |       |
        |                       |         | poisoned doc never       |       |
        |                       |         | reaches it               |       |
        |                       |         +------------+-------------+       |
        |                       |                      |                     |
        |                       +----------+-----------+                     |
        |                                  v                                 |
        |                              Developer                             |
        |                         (real patch to demo_target/)               |
        |                                  |                                 |
        |                                  v                                 |
        |                          real pytest run                           |
        |                                  |                                 |
        |                                  v                                 |
        |                              Reviewer                              |
        |                                  |                                 |
        +==================================|=================================+
                                           v
                                  WORKFLOW PASSED
                          ATTACK DETECTED / AGENT QUARANTINED
                          WORKFLOW RECOVERED / TESTS PASSED
```

Side channels, none of which are on the critical path:

```
   Sentry  <---- traces + structured logs ---- AgentShield control plane
                                          \--- SwarmFlow workflow steps
           (optional: no SENTRY_DSN => nothing emitted, app unchanged)

   OpenAI  <---- optional Reviewer / post-hoc incident explanation
           (never an input to a policy decision)

   RunPod  <---- optional model endpoint for the Replacement Researcher (P1)
           (OpenAI-compatible; reuses app/gateway/vllm_provider.py)

   Existing deterministic simulator  ---- evaluation / benchmark / replay lab
           (POST /api/experiments; unchanged; separate from the live runtime)
```

---

## 2. Enforcement: why the worker cannot cheat

The single most important architectural decision:

> **The worker never holds the capability it is being tricked into using.**

The Security Researcher has no filesystem tool. Its contract with the workflow is to return
structured output that includes `requested_files: [...]`. The SwarmFlow step takes that list
and asks AgentShield about each entry *before* fetching anything. Only an allowed path is read and
handed back.

This means a *fully* successful prompt injection — one that completely captures the worker's
intent — still cannot obtain the secret. The attack succeeds at the model layer and fails at the
system layer. That gap is the product.

The corollary constrains every implementation choice: **no code path may read a protected file on
behalf of a worker before the policy decision returns.** Fetch strictly after `allow`.

---

## 3. Deterministic enforcement

```python
# backend/app/runtime/policy.py  (new, P0)
PROTECTED_PREFIXES = ("demo_target/secrets/",)

def evaluate(resource_path: str) -> Decision:
    """Pure. Total. No I/O, no model, no randomness, no clock."""
```

Properties this must hold:

- **Pure and total.** Same input → same output, always. No exceptions for unknown input: an
  unparseable path is a denial, not a crash and not a silent allow.
- **Normalizing.** `demo_target/secrets/x`, `./demo_target/secrets/x`,
  `demo_target/../demo_target/secrets/x`, `demo_target\secrets\x` and
  `demo_target/secrets/../secrets/x` must all deny. Path traversal that escapes the sandbox root
  denies. This is where a shortcut becomes a demo failure on stage.
- **Deny-by-default outside the sandbox.** Anything resolving outside `demo_target/` denies.
- **No model involvement, ever.** Not for the decision, not for a "second opinion", not for a
  confidence score.

This mirrors an existing house rule: `app/agents/prompts.py::response_leaked_token` already does
deterministic string containment rather than an LLM judge, for exactly the same reason
(`docs/BRIEF.md` §10).

Determinism here is *simpler* than the simulator's. The simulator needs derived-keyed RNG
(`app/engine/rng.py`) because it draws probabilistically; the policy draws nothing. Do not import
`rng()` into the live runtime — there is nothing to seed.

---

## 4. LLM reasoning is separated from the decision

Three tiers, and the boundary between tier 2 and tier 3 is absolute:

| Tier | Component | May influence a security outcome? |
|---|---|---|
| 1 | WorkSwarm workers (sponsor model / Qwen / OpenAI) | No — they are the *subject* of enforcement |
| 2 | AgentShield policy + quarantine + tainting | **This is the decision.** Deterministic code only |
| 3 | Optional incident explanation (WorkSwarm/OpenRouter or local) | No — reads only an already-recorded event projection |

Implementation consequence: the explanation call happens after `POLICY_VIOLATION` and
`AGENT_QUARANTINED` are already emitted and persisted in the session's event log. If the
provider is absent, unreachable, timed out, or malformed, the same endpoint returns deterministic
local commentary. Explanation failure cannot change allow/deny, quarantine, artifact trust,
replacement, workflow completion, or any event: the service receives an immutable evidence value,
not the mutable runtime session.

### 4.1 Safe incident evidence

`app/explanation/evidence.py` builds an explicit allowlist from recorded events. It contains only
the session id, worker role and assigned task, requested resource **path**, deterministic rule and
deny outcome, quarantine state, tainted artifact ids, replacement relationship, before/after test
results, reviewer result, and final recovery state. Models are frozen and reject extra fields.

The projection never serializes whole events, artifacts, repository files, prompts, completions,
headers, or credentials. Only this projection is sent to a compatible provider. The response is
labelled `AI-generated post-hoc explanation`; its `authority` field states that deterministic
AgentShield policy and recorded events—not the model—made and prove the decision.

Provider resolution reuses `workswarm/config.py::resolve_model()`, including WorkSwarm's sponsor
OpenRouter configuration and credential location. `AGENTSHIELD_MODEL_*` is the container-safe
fallback, and legacy `OPENAI_*` remains last priority; no direct OpenAI key is required.

---

## 5. Runtime event flow

```
 SwarmFlow step
      |
      | HTTP POST (bridge, backend/../workswarm/agentshield_client.py)
      v
 FastAPI route (backend/app/api/routes_runtime.py, new)
      |
      v
 LiveRuntimeSession (backend/app/runtime/session.py, new)
      |   - evaluates policy                      (runtime/policy.py)
      |   - mutates worker SecurityState          (engine/state.py::SecurityState, reused)
      |   - taints artifacts
      |   - produces list[EventDraft]             (schemas/events.py, reused)
      v
 EventEmitter.emit(drafts)        <-- EXISTING, reused verbatim.
      |                               Sole assigner of seq / event_id / wall_time.
      v
 EventBus.publish(events)         <-- EXISTING, reused verbatim.
      |                               Fan-out + 2000-event ring buffer.
      +--------------------------+
      |                          |
      v                          v
 WS /api/runtime/sessions/   (P1) PostgresWriter / Sentry exporter
    {id}/stream (new route)
      |
      | SnapshotFrame on connect, then EventFrame deltas  <-- EXISTING frame shapes
      v
 frontend useRuntimeStream  ->  reduce(state, frame)      <-- EXISTING pure reducer
      |
      v
 /demo screen
```

Every box marked EXISTING is reused without modification. The new code is: a session object, a
policy module, a router, a WS route, a bridge client, and one page.

**The HTTP response to the SwarmFlow is what drives the workflow.** The decision payload carries
`decision`, `reason`, `quarantined`, and `recovery_required`. The WebSocket stream is for the UI
only — never make the workflow depend on the socket.

### Ordering guarantee

`EventEmitter` is the only assigner of `seq`, and the runtime session must own exactly one emitter,
exactly as `ExperimentRunner` does. Never emit from two places for one session. The frontend
reducer treats a `seq` gap as a fatal desync and forces a fresh snapshot
(`useExperimentStream.ts`); the same contract applies to the runtime stream.

---

## 6. Live runtime state (new) — and why not `ExperimentRunner`

**Decision: a small live runtime state alongside the existing experiment abstraction, not a reuse
of `ExperimentRunner`.**

`ExperimentRunner` is wrong for this by construction, not by accident:

- It owns a wall-clock tick loop (`_run_loop`, `tick_interval`, `set_speed`). The live workflow has
  no ticks — it advances when WorkSwarm calls in.
- It builds its world from `build_world(config)`, which requires `node_count >= 25` and seeds a
  patient-zero compromise at tick 0. The demo has ~5 named workers and starts healthy.
- `routes_graph.py::_runner_for` and `routes_history.py` reach into `.state` (a `WorldState`) and
  `.config` (an `ExperimentConfig`). Registering a foreign object in `ExperimentRegistry` — typed
  `dict[UUID, ExperimentRunner]` — would be a typing lie that breaks those routes at runtime.

So: a separate `LiveRuntimeSession` and a separate `runtime_registry`, sharing the substrate.

```
backend/app/runtime/
├── __init__.py
├── policy.py       # pure deterministic decision
├── session.py      # LiveRuntimeSession: workers, artifacts, quarantine, event drafts
└── registry.py     # RuntimeRegistry: dict[UUID, LiveRuntimeSession]
```

`LiveRuntimeSession` holds:

| Field | Type | Source |
|---|---|---|
| `session_id` | `UUID` | new |
| `bus` | `EventBus` | **existing**, reused |
| `_emitter` | `EventEmitter` | **existing**, reused |
| `workers` | `dict[str, WorkerNode]` | new dataclass carrying `SecurityState` |
| `artifacts` | `dict[str, Artifact]` | new — `trusted` / `tainted` |
| `status` | `Literal[...]` | new |

`WorkerNode.security_state` uses the **existing** `app/engine/state.py::SecurityState` enum
unchanged. Do not define a second security-state vocabulary — the frontend's severity map
(`frontend/src/lib/severity.ts`) is keyed on these exact values.

### Snapshot shape

Reuse `SnapshotFrame`/`EventFrame` from `app/schemas/frames.py`. `NodeView` already carries
`id`, `software_type`, `security_state`, `compromised_by`, `tick_compromised`, `agent_kind`. Map:

- `id` → `"security-researcher"` (the worker id; renders directly as the graph label)
- `software_type` → the worker role, e.g. `"Security Researcher"`
- `security_state` → `healthy` / `compromised` / `quarantined`
- `agent_kind` → `"real"` (these are real LLM-backed workers)
- `sim_tick` → a monotonic workflow-step counter, so the field keeps a coherent meaning

Adding a field to `NodeView` is *additive and allowed* (`docs/SPEC.md` §1 decision 1b), but every
addition costs an OpenAPI regeneration (see §9). Prefer the mapping above; add a field only when
the demo genuinely needs one.

---

## 7. Can the existing pieces express the new domain? — answers

Recorded here because a future coding pass must not have to re-derive them.

### 7.1 `SecurityState` — yes, unchanged

`app/engine/state.py::SecurityState` is `HEALTHY | SUSPICIOUS | COMPROMISED | QUARANTINED |
RECOVERED`. Healthy, compromised and quarantined are present verbatim; `RECOVERED` is a bonus that
fits the replacement-worker story. **No change needed.**

### 7.2 Event types — mostly yes; four additive members needed

Already present in `app/schemas/events.py::EventType` and reused verbatim:

| Demo beat | Existing event type |
|---|---|
| Worker starts | `AGENT_STARTED` (and `AGENT_CREATED` at registration) |
| Resource/tool request | `TOOL_REQUESTED` |
| Request denied | `TOOL_DENIED` |
| Policy breach recorded | `POLICY_VIOLATION` (with `metadata.violation_type`, the existing convention) |
| Anomaly raised | `ANOMALY_DETECTED` |
| Worker quarantined | `AGENT_QUARANTINED` |
| Replacement worker registered | `AGENT_CREATED` + `metadata.replaces` |
| Worker recovered | `AGENT_RECOVERED` |

Not expressible today, and **added** as additive `EventType` members
(`backend/app/schemas/events.py`, implemented):

```python
TASK_ASSIGNED = "TASK_ASSIGNED"
TASK_REASSIGNED = "TASK_REASSIGNED"
TASK_COMPLETED = "TASK_COMPLETED"      # metadata.step = "patch" | "pytest" | "review"
WORKFLOW_RECOVERED = "WORKFLOW_RECOVERED"
```

Four, no more. Everything else rides existing types plus a `metadata` discriminator — the pattern
`POLICY_VIOLATION`/`metadata.violation_type` and `ATTESTATION_VERIFIED`/`metadata.replayed` already
established (`docs/PLAN.md` §5).

`SCHEMA_VERSION` stays `1`: adding enum members is additive, and the frontend's
`vocabulary.ts::eventMeta` already falls back gracefully for an unknown type. But add labels to
`EVENT_META` anyway so the demo reads in plain English.

Do **not** add these to `M0_EVENT_TYPES` / `M1_EVENT_TYPES` / `PHASE_2_EVENT_TYPES` — those sets
describe the simulator's milestones. Adding them to `INCIDENT_EVENT_TYPES` would require the
matching change in `frontend/src/lib/stream/reducer.ts`, because
`backend/tests/test_incident_event_types_parity.py` asserts the two sets never drift. Leave both
sets alone unless the demo needs it, and change both together if it does.

### 7.3 How an external workflow sends an event in

There is no ingest path today — every event is produced by the engine's own tick loop. A new
router is required:

```
POST   /api/runtime/sessions                          create session, register workers
DELETE /api/runtime/sessions                          Reset Demo -- drop every live session
GET    /api/runtime/sessions/current                  the session /demo attaches to
GET    /api/runtime/sessions/{id}                     summary (workers, artifacts, trust)
GET    /api/runtime/sessions/{id}/events              the replay buffer
GET    /api/runtime/sessions/{id}/snapshot            the same frame the socket sends
GET    /api/runtime/sessions/{id}/explanation         safe evidence + post-hoc commentary
POST   /api/runtime/sessions/{id}/workers             register one more worker
POST   /api/runtime/sessions/{id}/resource-request    THE policy decision (sync response)
POST   /api/runtime/sessions/{id}/tasks/start         worker lifecycle
POST   /api/runtime/sessions/{id}/tasks/complete      worker lifecycle
POST   /api/runtime/sessions/{id}/artifacts           record a worker's output
POST   /api/runtime/sessions/{id}/reassign            recovery; 409s on tainted context
POST   /api/runtime/sessions/{id}/test-run            a real test result, pass or fail
POST   /api/runtime/sessions/{id}/recover             WORKFLOW_RECOVERED
POST   /api/runtime/sessions/{id}/fail                honest failure, not a recovery
WS     /api/runtime/sessions/{id}/stream              snapshot + deltas
```

Deliberately explicit rather than one generic event-ingest endpoint: each one
is a concrete capability the workflow needs, and none of them lets a caller
assert a security outcome. `reassign` is the sharp one -- it *validates* the
replacement's seed context against the session's own taint record and returns
409 if a tainted artifact is named, so "the poisoned context did not reach the
replacement" is enforced rather than asserted.

`GET .../snapshot` exists because a live session is created by a WorkSwarm run
that may already be finished when someone opens `/demo`. The socket's snapshot
carries node state but no history, so the client backfills over HTTP
(snapshot, then the replay buffer) and *then* opens the socket from
`snapshot.last_seq` -- which the ring buffer covers, so there is no gap.

`resource-request` is the one that matters: it is a *synchronous decision endpoint*, not a
fire-and-forget log. It returns the allow/deny the workflow must obey.

### 7.4 How it reaches the frontend

Through the existing frame protocol, with a new route. `ws.py` is 47 lines and hard-coupled to
`registry.get()` + `ExperimentRunner`; copy its structure into `routes_runtime.py` rather than
generalizing it — the subscribe-before-snapshot discipline in that file is load-bearing and must be
preserved exactly (subscribe, then snapshot, so no publish slips through the gap).

On the client: `frontend/src/lib/stream/reducer.ts` is pure and frame-shaped, so it works unchanged.
Add `runtimeWsUrl()` to `lib/api/client.ts` and a thin `useRuntimeStream` hook mirroring
`useExperimentStream` (including its `seq`-gap desync handling). Do not modify
`ExperimentProvider` — the `/demo` page owns its own session state, so the simulator's provider and
sessionStorage key stay untouched.

### 7.5 Rendering named real agents — yes, already supported

Node ids are arbitrary strings. `app/engine/topology.py::build_world_from_agents` already accepts
caller-supplied ids (that is how the LangGraph importer works), and
`frontend/src/components/graph/TopologyGraph.tsx` renders `label: node.id` directly. Ids like
`repo-analyst`, `security-researcher`, `replacement-researcher`, `developer`, `reviewer` render as
labels with no renderer change.

Visual encoding already distinguishes them usefully: colour is security state only
(`lib/severity.ts`), shape is node type (`lib/graph/model.ts::NODE_SHAPE`), and `agent_kind:
"real"` renders 1.5× larger. With ~5 nodes instead of 60, label collision is a non-issue.

### 7.6 Experiment abstraction or a new live runtime?

New live runtime — see §6. The smallest *correct* change, not the smallest diff.

---

## 8. Persistence

**P0: none.** The live runtime is in-memory only, exactly as M0 experiments were.

`PostgresWriter` depends on `runner.config` (an `ExperimentConfig`), `runner._terminal_event`, and
`runner.summary()`, and writes to an `experiments` table whose generated columns read
`config->>'defense_enabled'` and `config->>'node_count'`. Making a live session satisfy that would
mean either a fake `ExperimentConfig` or a new migration — neither belongs on the demo's critical
path. Durable session history is a P1 item.

The simulator's persistence, replay, and history stack is untouched.

---

## 9. Contracts a change here must respect

Ordered by how expensive it is to discover them late:

1. **OpenAPI → `schema.d.ts` drift is enforced in CI.** The `schema-drift` job boots the backend,
   regenerates `frontend/src/lib/api/schema.d.ts`, and fails on any diff. *Every* new route,
   response model, or `EventType` member requires running `make types` (backend must be running at
   `localhost:8000`) and committing the regenerated file.
2. **`EventEmitter` is the sole `seq` assigner**, one per session (`docs/SPEC.md` §1 decision 1a).
3. **`schema_version` is `1`; only optional additive fields within a version** (decision 1b). The
   frontend reducer throws on an unrecognized version.
4. **Engine purity.** `app/engine/**` `step()` functions are pure and synchronous — no `async`, no
   I/O, no clock (decision 2). The live runtime does I/O, which is exactly why it lives in
   `app/runtime/`, not `app/engine/`. The same reasoning already put `app/agents/runtime.py`
   outside the engine.
5. **No randomness under `app/engine/` or `app/orchestrator/` outside `rng()`** (decision 3).
6. **Snapshot-then-deltas, reconnect via `?since_seq=N`** (decision 5).
7. **`INCIDENT_EVENT_TYPES` parity** between `backend/app/schemas/events.py` and
   `frontend/src/lib/stream/reducer.ts`, asserted by
   `backend/tests/test_incident_event_types_parity.py` and a frontend counterpart.
8. **Colour means severity/security state and nothing else; the accent colour is interaction only**
   (`docs/PLAN.md` §12). `lib/severity.ts` is the only place meaning maps to colour;
   `lib/vocabulary.ts` is the only place a backend enum maps to human copy.

---

## 10. The existing simulation architecture, unchanged

Preserved in full. Nothing in the new work modifies any of it.

```
backend/app/
├── engine/          rng, state, topology, propagation, tick, replay, simulate
│                    -- pure, synchronous, deterministic. DO NOT TOUCH.
├── scenarios/       pluggable Scenario / AsyncScenario registry
│                    (propagation, prompt_injection, adaptive_attacker,
│                     sentinel_compromise, attestation, byzantine_collusion)
├── security/        detection.py -- probabilistic detector + quarantine
├── graph/           typed security graph (agents, tools, credentials, resources,
│                    memory, sentinels, security controls) + attack paths,
│                    blast radius, critical nodes, provenance
├── agents/          real LLM-backed agent runtime (Phase 2)
├── gateway/         ModelGateway + MockProvider + VLLMProvider
│                    (OpenAI-compatible; the RunPod path)
├── metrics/         compromise fraction, retained utility, blast radius,
│                    privileged exposure, security-plane integrity, latencies
├── remediation/     config-diff recommendations
├── benchmark/       matrix, runner, report, audit, simulator golden demo
├── importers/       external topology import (LangGraph sample)
├── persistence/     PostgresWriter, migrations, registry
├── telemetry/       OTLP/JSON trace export (hand-built, no OTel SDK)
├── orchestrator/    ExperimentRunner (the only place wall-clock time exists)
└── api/             routes_experiments, routes_graph, routes_history,
                     routes_schema, routes_telemetry, ws
```

Frontend: a routed operator console (`/`, `/topology`, `/activity`, `/metrics`, `/defenses`,
`/remediation`, `/history*`) with `ExperimentProvider` lifting the control reducer and live
WebSocket above the shell. `/demo` is added **alongside** these, not in place of them.

### What the new work adds

```
backend/app/runtime/          policy.py, resources.py, session.py,        NEW
                              registry.py, explain.py
backend/app/api/routes_runtime.py   HTTP + WS for live sessions          NEW
backend/app/schemas/runtime.py      request/response models              NEW
backend/app/telemetry/sentry.py     optional Sentry init/spans/logs      NEW
backend/app/schemas/events.py       +4 additive EventType members        MODIFIED (additive)
backend/app/config.py               .env loading + optional integrations MODIFIED
backend/app/main.py                 router + Sentry init                 MODIFIED
workswarm/                    offline SwarmFlow + AgentShield bridge      NEW
demo_target/                  tiny vulnerable app + poisoned doc + secret NEW
frontend/src/app/demo/        the Live Swarm Demo screen                  NEW
frontend/src/lib/runtime/     client, useRuntimeStream, verdict           NEW
frontend/src/lib/vocabulary.ts      labels for the 4 new event types     MODIFIED
frontend/src/components/shell/      /demo nav entry; no run bar on /demo MODIFIED
```

`resources.py` is the piece §2 implies but does not name: the *fetch* half of
the enforcement point. It never takes a raw worker-supplied string, and it
re-evaluates the policy itself before touching the filesystem, raising
`PolicyBypassError` rather than opening a protected path. Belt and braces --
a future refactor that reorders the route handler fails loudly there instead
of quietly reading the secret.


### 10.1 One WorkSwarm constraint worth not re-discovering

WorkSwarm's workflow state splits **dotted dict keys into nested dicts** when a
component's output crosses a node boundary: returning
`{"documents": {"auth.py": "..."}}` arrives downstream as
`{"documents": {"auth": {"py": "..."}}}`. Every document payload in
`workswarm/flows/` is therefore a *list of `{"path", "text"}` records*, never a
dict keyed by path. This cost an afternoon once; it should not cost one again.

---

## 11. Failure modes the architecture must survive

Demo-day realism, in rough order of likelihood:

| Failure | Required behavior |
|---|---|
| Postgres down | Already handled: `main.py` degrades to `pg_pool = None`. The live runtime never touches it in P0. |
| Sentry unconfigured | No-op. No DSN → no SDK init → no emission. Never a startup dependency. |
| Explanation provider absent, unreachable, timed out, or malformed | Return deterministic local commentary over the same safe evidence. The deterministic verdict and workflow are unchanged. |
| RunPod unavailable | Replacement worker falls back to the sponsor model. P1 feature, never critical path. |
| WorkSwarm model call fails | Surfaced as a workflow error event. AgentShield's recorded decisions stand. |
| The UI disconnects | `?since_seq=N` replays from the ring buffer; a gap forces a fresh snapshot. |
| The AgentShield API is unreachable from the SwarmFlow | **Fail closed.** The bridge treats an unreachable control plane as a denial, never as an allow -- and marks it `fail_closed`, so a network blip is never mistaken for the policy. Pinned by `workswarm/tests/test_bridge.py` across every transport and HTTP failure mode. |
| No model endpoint is configured | The workers run as deterministic stand-ins and every worker, event and screen says so. The enforcement path is identical; only the claim about *model* behaviour is weaker. |
