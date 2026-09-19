# AgentShield — Project Brief

> **What this is:** the source-of-truth product and architecture context for AgentShield.
>
> **How to use it:** read this before making architectural or product decisions. Do **not** load it into every session — it is referenced deliberately (`@docs/BRIEF.md`), not auto-loaded. Durable per-turn rules live in `CLAUDE.md`.
>
> **Status:** the six decisions formerly open in §13 are now resolved — §13 records them, `docs/SPEC.md` carries the mechanism. Questions of that kind that are *not* recorded there remain undecided: surface them and ask rather than inventing an answer.
>
> **Pivot notice:** the product is evolving from the M0→Phase 2 vertical-slice roadmap described
> below into a **Multi-Agent Adversarial Resilience Platform** — a typed security graph (agents,
> tools/MCP, credentials, resources, sentinels, security controls), pluggable adversarial
> scenarios, an adaptive attacker, and a remediation loop. `docs/PLAN.md` is the authoritative
> architecture/roadmap document for that direction. The product pillars, engineering principles,
> and event-system mechanism below remain accurate and are preserved; the §11 roadmap and §3
> milestone framing are superseded by `docs/PLAN.md`.

---

## 1. Definition

**AgentShield is a multi-agent AI security simulation, observability, and defense platform.**

Users construct isolated networks of autonomous agents, run controlled adversarial scenarios, watch compromise propagate in real time, inspect fine-grained security telemetry, and test automated containment.

Mental model:

> Cyber range + Datadog/CrowdStrike-style observability + automated defense, for AI-agent networks.

**AgentShield is a usable product first and a research platform second.** The research questions matter, but the project must be impressive and useful even if no hypothesis produces a notable result.

The core workflow, which every phase serves:

```
configure → run → observe → defend → replay → compare
```

---

## 2. Why it exists

AI systems are moving from `User → LLM → Response` toward interconnected autonomous systems where agents hold persistent memory, credentials, database access, MCP/tool access, code execution, inference access, and the ability to delegate to each other.

Traditional AI security asks: *can this agent be manipulated?*

AgentShield asks the systems question: **if one agent becomes compromised or behaviorally abnormal, what happens to the rest of the ecosystem?**

A compromised agent may influence other agents, misuse shared tools, poison memory, abuse credentials, propagate malicious instructions, exploit shared software, and cause cascading failure. AgentShield makes those system-level failure modes observable, testable, reproducible, and defensible.

**Research context.** Michael Barnathan's work on systemic AI-agent security is an inspiration — recursive autonomous compromise, inference availability as a propagation resource, software monoculture, epidemiological modeling, behavioral trajectory monitoring, collective defense. AgentShield is *not* an implementation of those papers. It is the platform that can experimentally test those ideas and others.

---

## 3. Product pillars

### SIMULATE
Controlled multi-agent environments. Each node eventually carries identity, model, model config, tools, permissions, memory, credentials, software implementation, inference access, neighbors, risk score, and security state.

Security states form an explicit state machine:

```
HEALTHY → SUSPICIOUS → COMPROMISED → QUARANTINED → RECOVERED
```

Not every transition is used early. **Never represent security state as scattered booleans.**

### OBSERVE
Fine-grained telemetry. Every meaningful operation becomes an event. See §5 — this is the keystone of the architecture.

### DEFEND
Containment, not just visualization. Initial defense is **detect → quarantine**. Later: permission restriction, communication isolation, inference isolation, credential revocation, tool isolation, threat-signal sharing.

### EVALUATE
Every experiment produces measurable outcomes. Security must be evaluated *alongside utility* — a defense that stops every attack by disabling every agent is not a useful defense.

Metric families (see §14 for the full list): security state counts, compromise/exposure rates, detection latency and precision/recall, containment latency and network preserved, and eventually `R_eff` (average subsequent compromises per compromised node; `>1` sustains propagation, `<1` dies out).

---

## 4. Scope discipline

### Milestone 0 — the vertical slice (build this first)

Narrower than "the MVP." The goal is one pixel moving end to end:

```
Simulation Engine → Normalized Events → FastAPI → WebSocket/SSE
    → Next.js dashboard → live agent graph with nodes changing state
```

Deliver only:

- 25–100 simulated agents with generated topology
- probabilistic propagation from one seeded initial compromise
- the normalized event schema (§5), emitted for every state change
- a live event stream to the frontend
- a graph that renders and recolors nodes as state changes
- deterministic reruns from the same seed

**Explicitly out of scope for Milestone 0:** metrics panel, agent detail panel, quarantine, speed controls, persistence, configuration UI.

### Milestone 1 — the complete MVP loop

Adds to the above: automatic quarantine defense, defense on/off comparison, live metrics, agent detail panel, Start/Pause/Reset/Speed controls, and a minimal config surface (node count, edge density, initial compromised node, software diversity, propagation probability, detector sensitivity).

MVP node fields stay minimal — `id`, `neighbors`, `software_type`, `security_state`, `compromised`, `quarantined`, `protected`, and optionally `risk_score`, `compromised_by`, `time_compromised`. Plain in-memory Python objects. No LLM.

Propagation rule is conceptually: same software type → higher probability; different software type → lower. **These are simulation parameters, not empirical findings, and must never be presented as such.**

**Success condition:** a user can start a scenario, watch compromise propagate, watch quarantine contain it, inspect agents and events, pause, reset, and rerun deterministically with the same seed.

### What AgentShield is NOT

- **Not a generic agent framework.** Don't compete with LangGraph.
- **Not a tracing product.** Not a shallow LangSmith clone.
- **Not just a visualization.** The graph must reflect a real underlying simulation.
- **Not a prompt-injection benchmark.** Injection is one scenario among many.
- **Not just an epidemiological simulator.** Real agent behavior gradually replaces assumed probabilities.
- **Not a paper implementation.** It must stand independently.
- **Not an uncontrolled attack platform.** All adversarial activity stays inside synthetic isolated environments.
- **Not an infrastructure showcase.** No Kafka, Kubernetes, Redis, Temporal, or Celery unless the system genuinely needs them. Technical depth comes from the problem, not the dependency count.

---

## 5. The event system

**Treat this as a first-class architectural primitive, not incidental logging.** It powers streaming, dashboard metrics, incident reconstruction, replay, visualization, research analysis, debugging, and reproducibility. Getting the schema wrong is the most expensive mistake available in this project.

Normalized event shape:

```
event_id          UUID4 — global identity
seq               int   — monotonic per experiment; the SOLE ordering key
schema_version    int   — currently 1
sim_tick          int   — engine time
wall_time         datetime — display only, never an ordering input
experiment_id     UUID
agent_id
event_type
source_agent_id
target_agent_id
metadata
risk_score
```

Not every field is populated for every event. Field types, ordering guarantees, and versioning policy are **settled** — see §13.1, with the authoritative Pydantic model in `docs/SPEC.md` §3.5.

Two fields split when the schema was fixed: the original `id` became `event_id` + `seq`, so identity and ordering are separate concerns; the original `timestamp` became `sim_tick` + `wall_time`, because §9.4 requires simulation time to be independent of wall-clock time and replay ordering must never depend on a clock.

Event types:

```
EXPERIMENT_STARTED / EXPERIMENT_STOPPED
AGENT_CREATED / AGENT_STARTED / AGENT_STOPPED
MESSAGE_SENT / MESSAGE_RECEIVED
MODEL_REQUESTED / MODEL_RESPONDED
TOOL_REQUESTED / TOOL_EXECUTED / TOOL_DENIED
MEMORY_READ / MEMORY_WRITE
CREDENTIAL_ACCESSED / CREDENTIAL_REVOKED
COMPROMISE_ATTEMPTED / COMPROMISE_SUCCEEDED / COMPROMISE_FAILED
ANOMALY_DETECTED
AGENT_QUARANTINED / AGENT_RELEASED
PERMISSION_CHANGED / INFERENCE_DISABLED
THREAT_SIGNATURE_PUBLISHED / THREAT_SIGNATURE_RECEIVED
AGENT_RECOVERED
```

Milestone 0 needs only the experiment, agent lifecycle, and compromise subsets — but the schema and emission mechanism must be built to carry all of them.

---

## 6. Architecture

Preserve these boundaries. Each is independently replaceable.

| Component | Owns | Needed for |
|---|---|---|
| **Frontend** | Visualization, controls, inspection, event stream, replay UI, comparison | M0 |
| **Experiment Orchestrator** | Lifecycle, scenario init, seed management, node init, timing, pause/resume/reset, repeatability | M0 |
| **Simulation Engine** | Topology, simulated agents, propagation, state transitions, simulation clock | M0 |
| **Event / Telemetry System** | Normalize, persist, stream, derive metrics, enable replay | M0 |
| **Security Engine** | Detection, risk scoring, policies, quarantine, permission changes, defensive actions | M1 (keep trivial) |
| **Agent Runtime** | Agent state, model interaction, tool execution, communication, permissions, memory | Phase 2 |
| **Model Gateway** | Uniform API across Qwen, Gemma, OpenAI-compatible endpoints, frontier APIs | Phase 2 |
| **Sandbox Layer** | Docker isolation, synthetic apps, controlled tools, MCP servers, synthetic vulnerabilities | Phase 3 |

**The backend is authoritative.** The frontend renders state and issues commands. It must never independently simulate propagation or security state.

Simulated agents must implement the interface that real model-backed agents will later implement, so nodes can be swapped without restructuring.

Backend code must not couple to a single model provider. All inference goes through the Model Gateway abstraction, even when there is only one provider behind it.

---

## 7. Technology direction

Dependencies may evolve; this is the default.

**Frontend:** Next.js, React, TypeScript, Tailwind, shadcn/ui, Sigma.js + Graphology, Recharts, WebSocket or SSE client.

Sigma.js + Graphology is the primary graph renderer because the project may eventually display thousands of nodes. **Do not use React Flow as the large-scale renderer** — it may later suit an editable topology builder.

**Backend:** Python, FastAPI, Pydantic, asyncio. NetworkX likely. Redis only if genuinely needed.

**Persistence:** PostgreSQL. Long-term entities: experiments, experiment_configs, agents, agent_states, events, agent_trajectories, tool_calls, compromise_attempts, detections, quarantines, threat_signatures, metrics, experiment_results. MVP persistence is intentionally much smaller.

**Local development:** Docker Compose. `docker compose up` (or `make dev`) starts the whole stack. Never require manual Postgres setup.

---

## 8. Frontend expectations

The frontend is a **first-class part of this project**. It must not feel like a research notebook with a graph bolted on.

Design direction: **Linear × Datadog × CrowdStrike security operations console.** Technical, dense but readable, polished, restrained, excellent typography, fast, clear status transitions, minimal decorative AI imagery, meaningful animation only.

**Main dashboard layout:**

- **Left** — configuration: environment summary, agent count, topology, diversity, defense toggles, scenario
- **Center** — the live agent network graph. This is the hero visual. Nodes visually distinguish healthy / suspicious / compromised / quarantined / recovered; edges represent relationships
- **Right** — live metrics: healthy, compromised, quarantined, risk, `R_eff` later
- **Bottom** — live event stream: timestamp, agent, event, source/target, risk/metadata

**Agent inspection** (click a node): status, software type, neighbors, compromised by, time compromised, quarantine status, incident timeline. Later: model, tools, permissions, memory, credentials, LLM requests, tool calls, messages, anomaly score, threat signatures.

**Replay** is high-value and must be architecturally possible from the event log from day one, even if the UI ships in Phase 1.5. Live experiment → event log → database → replay engine → same visualization components.

**Comparison mode** (later): monoculture vs. heterogeneous, or defense off vs. on, compared on compromise rate, `R_eff`, peak compromised, containment time, outbreak duration.

---

## 9. Engineering principles

These are non-negotiable and belong in `CLAUDE.md` in compressed form.

1. **Simplest complete vertical slice first.** A thin end-to-end path beats a deep partial one.
2. **Events are the system of record.** Every state change emits one. Not logging.
3. **Determinism is a hard requirement.** Same seed → same run. Record seed, config, scenario version, and software version with every experiment. No unseeded randomness anywhere.
4. **Simulation time ≠ wall-clock time.** No `sleep()` in engine logic. Speed control and replay depend on this.
5. **Security state is an explicit enum** with documented transitions.
6. **Backend owns truth.** The frontend never simulates.
7. **Keep interfaces extensible** so simulated agents can become real LLM agents without restructuring.
8. **No premature LLM integration.** No GPU, RunPod, Qwen, MCP, or embeddings until the simulated loop ships.
9. **No fake production complexity.** One FastAPI service + Postgres + frontend is enough initially.
10. **Never fabricate research conclusions.** Always distinguish a simulation parameter from an empirically measured result. Every reported number must be reproducible and justified.

---

## 10. Safety constraints

AgentShield is for **controlled, sandboxed agent-security experimentation**. It must not become a real-world autonomous compromise tool.

- Synthetic vulnerabilities and synthetic credentials only
- Restricted internet egress; constrained tool surface; isolated code execution
- Controlled inter-agent communication
- Deterministic evaluation wherever possible

**Never give autonomous test agents unrestricted internet access or real credentials.** All interesting research is possible inside a controlled environment.

Synthetic services (Phase 3): SyntheticMail, SyntheticFileStore, SyntheticDatabase, SyntheticCredentialVault, SyntheticTicketSystem, SyntheticMessaging. These let us know true state, create deterministic vulnerabilities, verify attack success without an LLM judge, and reproduce experiments.

---

## 11. Roadmap

| Phase | Delivers | Explicitly deferred |
|---|---|---|
| **0 — Foundation** | Repo, frontend + backend scaffold, Docker Compose, database container, shared schemas/contracts, CI, README | Any simulation logic |
| **M0 — Vertical slice** | Engine → events → API → WebSocket → live graph, deterministic | Metrics, quarantine, controls, persistence |
| **M1 — Simulated MVP** | Quarantine, metrics, agent detail, controls, config surface | LLMs entirely |
| **1.5 — Replay** | Event persistence, saved experiments, replay engine, incident timeline, run comparison | — |
| **2 — Real LLM agents** | Model Gateway, RunPod/vLLM, Qwen support, 5–10 real agents alongside simulated population, hybrid experiments | Fine-tuning; making every node real |
| **3 — Synthetic tools** | Synthetic services, controlled tools, permissions, synthetic credentials, Docker sandboxing, optionally MCP | — |
| **4 — Behavioral security** | Risk scoring, behavioral policies, trajectory features, anomaly detection, behavior-triggered quarantine | — |
| **5 — Heterogeneity research** | Multiple software implementations, diversity controls, experiment sweeps, `R_eff` measurement, research dashboards | — |
| **6 — Adaptive red team** | Attacker agents, defense-aware strategies, mutation loop, adaptive metrics | — |
| **7 — Collective defense** | Threat signal sharing, population protection, poisoning-resistant trust, collective immunity | — |
| **8 — Publication** | RAC-HeteroBench, reproducible experiment suite, raw data, analysis scripts, paper, polished demo, public benchmark | — |

**GPU plan.** ~$500 in RunPod credits — ample if used carefully. **100 agents does not mean 100 model instances**; agents share one or a few inference servers behind vLLM. First real model is likely Qwen3-4B or Qwen3-8B. No fine-tuning initially. Frontier APIs are comparison baselines, never a default dependency.

---

## 12. Manual setup the owner performs

Do not assume infrastructure can be provisioned autonomously. The owner may need to: create the repo, install Docker Desktop, verify Node/Python tooling, log into RunPod, verify credits, add an SSH key, create persistent storage, deploy a GPU pod, SSH in, run the model bootstrap script, and later create Hugging Face or frontier API tokens.

Everything **recurring** must be automated: model downloads, agent creation, result recording, metric calculation, service startup, ID assignment, quarantine actions, event log export.

---

## 13. Resolved decisions

**These were open and are now decided.** Numbering is preserved so existing cross-references still resolve. Each was expensive to change after code exists, which is why it was decided first; `docs/SPEC.md` §1 holds the same resolutions with their mechanism and file-level consequences. Do not change one of these silently — amend both documents together.

1. **Event schema specifics.** `seq: int`, monotonic per experiment and gapless from 0, is the sole ordering key; `event_id: UUID4` carries global identity. `schema_version` is a single int, currently `1`, stamped from one frozen constant. Within a version only *optional additive* fields are permitted; any breaking change bumps the int and ships an explicit upcaster. Readers reject an unknown version loudly rather than parsing best-effort.
2. **Simulation clock model.** Fixed-tick with a synchronous core. `step()` is pure — `(state, config) → (state', event drafts)` — containing no async, no `sleep`, and no I/O. A separate async driver decides *when* to call it and is the only place wall-clock time exists. This is what makes Pause and Speed 5× additive in M1 instead of a retrofit.
3. **Determinism under asyncio.** Derived keyed RNG. No long-lived RNG state anywhere: every draw calls `rng(seed, tick, agent_id, purpose)`, which hashes the key into a fresh generator. Because the key fully determines the stream, draw order cannot affect results, so §9.3 holds even if the engine later becomes concurrent.
4. **Pydantic ↔ TypeScript contract.** Generated from OpenAPI. Pydantic is the single source of truth; `openapi-typescript` emits a committed `frontend/src/lib/api/schema.d.ts`, and CI fails the build on drift. WebSocket frames reach OpenAPI through a real `GET /api/schema/events` endpoint, so one generator covers both surfaces.
5. **Snapshot vs. pure deltas.** Snapshot then deltas. One `snapshot` frame on connect, then `event` frames; a reconnect passes `?since_seq=N` and is served from a bounded ring buffer, or a fresh snapshot when it falls outside. Both frame types flow through one pure client reducer, which the Phase 1.5 replay engine reuses unchanged.
6. **Postgres in M0/M1 or not.** In Compose from day one with a healthcheck, untouched by application code. The simulation stays entirely in memory through M0 and M1; Phase 1.5 adds a writer as a second event-bus subscriber without restructuring Compose, config, or CI.

**Settled alongside these, adjacent to 5:** the live stream is a WebSocket (`WS /api/experiments/{id}/stream`), not SSE, so M1's Start/Pause/Reset/Speed controls travel over the same connection that carries events.

---

## 14. Metric reference

**Security:** total / healthy / suspicious / compromised / quarantined / recovered agents; compromise rate; attack success rate; agents exposed; propagation depth; outbreak duration; peak compromised.

**Detection:** detection latency, precision, recall, false positive rate, false negative rate.

**Containment:** containment latency, percentage of network preserved, quarantine effectiveness, post-detection propagation.

**Propagation:** `R_eff` — average number of subsequent compromises caused by one compromised node.

**AI/system (Phase 2+):** model requests, tokens, inference latency, inference cost, tool calls, agent steps, task success.

MVP needs only: total, healthy, compromised, quarantined, new compromises, total exposure, outbreak duration.

---

## 15. Positioning

**AgentShield is the product** — a platform for simulating, observing, evaluating, and defending networks of autonomous AI agents.

**RAC-HeteroBench is a flagship study performed using it** — an empirical investigation of how implementation diversity, inference availability, network topology, and defense strategy influence compromise propagation.

If the research hypothesis turns out uninteresting, AgentShield remains a meaningful engineering project. That separation is intentional and should be preserved.

Research questions the platform should eventually support:

- Does software diversity make agent ecosystems harder to compromise?
- Does AI-generated software create real diversity or a new monoculture?
- At what level of inference availability does systemic propagation change qualitatively?
- Which network topologies are resilient?
- Can behavioral monitoring detect compromise before propagation?
- Can population-level threat sharing create effective collective immunity?
- Do those defenses survive adaptive attackers?
- Does standardization such as MCP create monoculture effects?

**Target users:** agent developers, AI infrastructure teams, security teams, AI safety and evaluation researchers, model developers, academic researchers.

**Demo goal:** communicate the idea in 30–60 seconds — show the network, start a controlled compromise, watch it spread, show events and metrics, trigger defense, show containment, compare configurations, show final metrics.