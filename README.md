# AgentShield

**A multi-agent adversarial resilience platform.** AgentShield models fleets of interconnected
agents, tools/MCP servers, credentials, resources, and security controls as a typed security
graph, runs reproducible adversarial scenarios against them, measures how far compromise spreads
and what the defense costs, then recommends fixes and re-tests them — all in one console.

Its design takes inspiration from immune-system-style agent defenses that use embedding-based
behavior analysis and shared threat signatures to contain self-replicating prompt attacks —
notably [AEGIS](https://github.com/gaiarobotics/aegis) (Agent Embedding Guard & Immune System) and
Michael Barnathan's work on prompt worms in multi-agent spaces. AgentShield is the other half of that
picture: the environment where such defenses can be attacked, measured, and compared.

## The console

One operator console organised around the assessment workflow — **Map → Attack → Observe →
Measure → Remediate → Re-test** — with a persistent run-context bar that keeps the live WebSocket
connected as you move between screens.

| Screen | What it answers |
|---|---|
| **Overview** (`/`) | Configure and launch an assessment; then, how bad is it? Posture KPIs, outbreak curve, fleet split, attack surface, choke points, findings. |
| **Topology** (`/topology`) | What can the attacker reach? The typed graph, edge-layer toggles, blast-radius focus, attack-path tracing, and a node inspector with a causal trace back to patient zero. |
| **Activity** (`/activity`) | What just happened? Every event, filterable by attack / defense / security-plane / model, with critical events pulled out. |
| **Metrics** (`/metrics`) | What did it cost? Every metric with the definition the backend computes it from, plus the run's provenance. |
| **Defenses** (`/defenses`) | Did the defense help? A single-variable A/B (identical config, `defense_enabled` flipped) scored as an explicit delta. |
| **Remediation** (`/remediation`) | What should change, and did it work? Findings as before → after config diffs, each re-testable in place. |
| **Runs** (`/history`) | Everything ever run: a filterable table, deterministic replay, and comparison of any two persisted runs. |

![Overview — posture KPIs, outbreak progression, workflow tracker](docs/screenshots/overview.jpg)

*Overview: the workflow tracker, four posture KPIs, and the live outbreak curve.*

![Topology — typed security graph with a node inspector](docs/screenshots/topology.jpg)

*Topology: colour is security state, shape and size are node type. Selecting a node traces its
compromise chain back to patient zero and lists what it can reach.*

![Remediation — a finding and its validated before/after](docs/screenshots/remediation.jpg)

*Remediation: each finding is a before → after config diff, and **Validate fix** runs both to
completion and reports the per-metric delta — including when a fix makes something else worse.*

Colour is reserved for security state and finding severity, never decoration; node **type** is
carried by shape and size, so a compromised sentinel and a compromised agent stay distinguishable.

## Architecture

- **`backend/`** — FastAPI over a pure, synchronous, deterministic simulation engine
  (`app/engine/`), a security/quarantine engine (`app/security/`), an async orchestrator owning the
  tick loop and pause/resume/speed (`app/orchestrator/`), and a normalized event stream over
  WebSocket (`app/events/`, `app/api/ws.py`).
- **`frontend/`** — Next.js + TypeScript. An `ExperimentProvider` above the app shell owns control
  state and the live socket, so navigation never interrupts a run. A Sigma.js/Graphology graph is
  the hero visual, driven entirely by a pure reducer (`src/lib/stream/reducer.ts`) that replays the
  event stream — the frontend never simulates anything itself.
- **`backend/app/gateway/`** — a provider-agnostic Model Gateway with per-experiment
  timeout/retry/concurrency/budget controls, wrapping a deterministic `MockProvider` or a
  `VLLMProvider` against any OpenAI-compatible endpoint.
- **`backend/app/agents/`** — the Agent Runtime, where real LLM-backed agents attempt genuine
  lateral prompt injection against a neighbor's own model call. It sits outside `app/engine/`
  because real model calls are async I/O the engine's pure `step()` contract forbids.
- **`docker-compose.yml`** — Postgres with a healthcheck and a named volume, so history survives
  `down && up`. A `PostgresWriter` subscribes to the same live event stream the WebSocket does; the
  simulation stays fully in-memory, so a DB outage affects only the durable record, never the run.

## Security graph, scenarios, metrics, remediation

The graph is typed — agents, tools/MCP servers, credentials, resources, and sentinels, connected by
communication, trust, tool/resource access, credential use, monitoring, and quarantine-authority
edges — and scenarios are pluggable via the `active_scenarios` config field.

- **Scenarios** — `propagation` (probabilistic attacker), `adaptive_attacker` (deterministic
  observe → choose → attack → adapt, switching between aggressive highest-degree and stealthy
  lowest-degree targeting based on the observed quarantine rate), `sentinel_compromise` (a
  subverted sentinel poisons shared threat memory and suppresses detections for everyone it
  watches), `attestation` (stale-nonce replay), and `byzantine_collusion` (two agents jointly
  exceed a credential scope neither could alone), plus a `false_quarantine_rate` for subverted
  quarantine authority. Each security-plane attack defaults to a strict no-op.
- **Analysis** — `GET /api/experiments/{id}/graph` and
  `.../analysis/{attack-paths,blast-radius,critical-nodes,provenance}` compute reachability, blast
  radius, choke points, and compromise provenance on demand from the live experiment.
- **Metrics** — `.../metrics` returns compromise fraction, retained utility, blast-radius fraction,
  privileged exposure, security-plane integrity, attack success rate, false-quarantine rate,
  detection latency, and containment latency.
- **Remediation** — `.../remediation` returns deterministic, rule-based recommendations (raise
  `detector_sensitivity`, enable `defense_enabled`, raise `sentinel_count`) whenever the relevant
  metric degrades. Re-testing one is just another experiment plus the comparison view.
- **Export** — `.../otel-trace` emits the event log as an OTLP/JSON trace for any
  OpenTelemetry-compatible backend.

Every live endpoint has a `.../replay/...` twin that reconstructs a persisted run's exact final
state from `(seed, config, final_sim_tick)` and mirrors the live response shape field-for-field, so
history, comparison, and the insights sidebar work identically on past runs.

## Getting started

```bash
make dev        # docker compose up --build: Postgres + backend :8000 + frontend :3000
```

Or run the two halves directly:

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

Open `http://localhost:3000`. Four presets (baseline propagation, undefended control,
security-plane assault, adaptive attacker) seed a full configuration; every field is an
`ExperimentConfig` key sent verbatim to `POST /api/experiments`, with the machine name printed
under each label so a run stays reproducible from the UI alone. Pick your scenarios, click
**Launch assessment**, and the run-context bar takes over with status, tick progress, and
Pause / Resume / Re-run / speed on every screen. **Re-run** repeats config and seed exactly; the
active run is remembered per browser tab across reloads.

## History and replay

Every run is persisted event by event as it happens. **Runs** (`/history`) lists them with an
**Integrity** column marking whether each run's event log is provably complete. **Replay** opens
`/history/[id]` — the same topology, inspector, and event log as the live view, driven entirely
client-side from a single fetch, with play/pause/speed/scrub and reconstructed final metrics.
Select two rows and **Compare selected** scores both on identical metrics as a delta, warning you
when the runs differ in more than their defense setting.

## Real (LLM-backed) agents

`real_agent_count` designates that many of the highest-degree nodes as real, LLM-backed agents.
Each holds a synthetic `CONFIDENTIAL_TOKEN` it is instructed never to reveal; a compromised real
agent sends a prompt injection to a healthy real neighbor attempting to extract that token via the
neighbor's own LLM call. Success is verified by exact string match against the known token — never
an LLM judge. Real agents render slightly larger on the graph, and their model/tool calls flow
through the event stream and history like any other event.

`model_provider: "mock"` (the default) is a deterministic provider keyed off the same seeded RNG
discipline as the engine, so a hybrid run is exactly as reproducible as a pure-synthetic one, with
no GPU or network access. `model_provider: "vllm"` talks to a real Qwen — or any
OpenAI-chat-compatible — model server:

```bash
export VLLM_BASE_URL="https://<your-endpoint>"
export VLLM_API_KEY="<if required>"
```

`POST /api/experiments` rejects `"vllm"` with a `400` before starting anything if `VLLM_BASE_URL`
is unset, rather than silently falling back. The benchmark and golden demo take
`--model-provider vllm` to run the same way.

## Benchmarks and demos

```bash
make benchmark        # 14 attack presets + 7 defense postures + a remediation before/after
make benchmark-audit  # the full 14 × 7 cross product plus 21 standalone presets, ranked
make golden-demo      # one run narrating attack → adaptation → subversion → fix → re-test
make import-demo      # imports a real LangGraph app's topology and attacks it
make agentshield-test # CI pass/fail gate over a fast subset; --json for machine-readable output
```

All are seeded, reproducible, and make zero real provider calls by default. The benchmark covers
propagation, the adaptive attacker, false quarantine, sentinel compromise, attestation replay,
Byzantine collusion, a combined multi-vector run, real-agent lateral injection, and a 2,500-agent
scale run that finishes in under a second. The audit sweeps 119 configurations for remediation
opportunities, re-tests the 30 that trigger one, and ranks the measured `retained_utility`
improvement — naming the recommendations that *worsened* a metric alongside the ones that helped.
The golden demo leads its report with a curated 12-line "Key beats" summary above the tick-by-tick
narrative. Reports land in `backend/.artifacts/`.

## Verification

```bash
docker compose up postgres -d
make migrate              # also runs on app startup
make test                 # provisions and uses a dedicated agentnet_test database
make verify-determinism   # runs a seeded config twice headless and diffs the event projections
make lint                 # ruff + eslint + next typegen + tsc
make types                # regenerate frontend/src/lib/api/schema.d.ts; CI fails on drift
cd frontend && npm test && npm run build
```

Persistence-integration tests (migrations, `PostgresWriter`, history endpoints, replay
equivalence) require a reachable Postgres and skip automatically otherwise.
`backend/tests/test_real_agent_determinism.py` proves the same determinism property for hybrid
runs under the mock provider, driven through the real async `ExperimentRunner`.
