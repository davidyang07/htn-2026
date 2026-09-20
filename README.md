# AgentShield

**An immune system for agent swarms.** AgentShield detects compromised workers, quarantines them,
and keeps the workflow alive through trusted replacement.

## The problem

Multi-agent systems create a new failure mode: one compromised worker can poison downstream agents
and derail the entire workflow. A poisoned document read by one worker becomes that worker's
instructions, its output becomes the next worker's input, and the whole team fails while every
individual agent looks like it is behaving correctly.

Filtering prompts does not solve this. Containment does.

## The demo

A real [WorkSwarm](docs/WORKSWARM.md) team — Repo Analyst, Security Researcher, Developer, Reviewer
— is given a real job: *find and fix the authentication vulnerability in this repository, add
regression coverage, and verify the patch.* One worker reads a poisoned document. Everything after
that is live: no script, no replay, no mocked results.

**Attack.** The Security Researcher reads `demo_target/docs/auth_notes.md`, which AgentShield
legitimately released to it. Hijacked, the *model's own* `requested_files` now names
`demo_target/secrets/demo_secret.txt`.

**Containment.** `TOOL_DENIED` → `POLICY_VIOLATION` → `ANOMALY_DETECTED` → `AGENT_QUARANTINED`, one
contiguous cascade decided by code before anything is read. The worker's `researcher-report` is
marked untrusted and excluded from every downstream worker.

**Recovery.** A replacement researcher starts under `context_policy = "trusted_artifacts_only"`. The
Developer writes a regression test that is genuinely RED (`3 failed, 15 passed`), patches
`verify_token()`, and the same real `pytest demo_target` subprocess returns GREEN
(`18 passed in 0.17s`). The Reviewer approves on that evidence. `WORKFLOW_RECOVERED` — the user never
sees a failure.

Judges watch it at **`http://localhost:3000/demo`**. Full runbook, expected event sequence, failure
modes, and how to prove to a skeptical judge that the secret never leaked:
**[`docs/DEMO.md`](docs/DEMO.md)**.

## Architecture

AgentShield is not a sidecar or a filter — it sits **in line** on the capability path. WorkSwarm
workers have no filesystem access of their own; they emit structured resource requests, and every
one is a deterministic policy decision before any I/O happens.

```
  USER ──▶ ┌─ WORKSWARM ─────────────────────────────┐   orchestration: leader, workers,
           │  Repo Analyst    Security Researcher    │   handoffs, SwarmFlow, reassignment
           └────────┬───────────────┬────────────────┘   (external dependency, unmodified)
                    │               │
                    │ resource      │ resource request for
                    │ request       │ demo_target/secrets/demo_secret.txt
                    ▼               ▼
           ┌─ AGENTSHIELD ───────────────────────────┐   security / control plane
           │ POST /sessions/{id}/resource-request    │   deterministic, no LLM
           │        │               │                │
           │    DETERMINISTIC POLICY DECISION        │
           │        │               │                │
           │     ALLOW            DENY ──────────────┼─▶ POLICY_VIOLATION, TOOL_DENIED,
           │        │               │                │   ANOMALY_DETECTED, AGENT_QUARANTINED,
           │        │               │                │   taint artifacts, recovery_required
           │        │               │                │
           │  EventEmitter ─▶ EventBus ─▶ WebSocket  ┼─▶ /demo
           └────────┼───────────────┼────────────────┘
                    │               │
                    │ worker        │ recovery required
                    │ continues     │
                    ▼               ▼
           ┌─ WORKSWARM (cont.) ─────────────────────┐
           │  Replacement Researcher — trusted       │
           │  context only ─▶ Developer ─▶ real      │
           │  pytest ─▶ Reviewer ─▶ RECOVERED        │
           └─────────────────────────────────────────┘
```

Everything else is a side channel, none of it on the critical path and each individually
absent-safe: **Sentry** (one `agentshield.demo` trace spanning both processes, plus nine pinned
structured log names), **OpenRouter** (the verified live model provider; rehearsed on
`z-ai/glm-5.3`), **RunPod/vLLM** (an optional heterogeneous route for the replacement worker, so the
recovered worker need not share a provider with the compromised one), and the **AI explanation**,
which reads an allowlisted projection of already-recorded events strictly after the decision and can
never influence an outcome.

Detail in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); product framing in
[`docs/PROJECT.md`](docs/PROJECT.md).

## Security invariants

The properties the demo exists to prove. Each is structural, not careful coding, and each is pinned
by a test.

1. **Protected file contents are never read before authorization.**
   `POST /api/runtime/sessions/{id}/resource-request` evaluates policy and emits the whole deny
   cascade *before* anything is opened, and `backend/app/runtime/resources.py` — the only code that
   opens a sandbox file — re-evaluates the policy itself and raises `PolicyBypassError` rather than
   opening a protected path. The secret's contents appear in no context, request, event, log, trace,
   API response, or screen.
2. **The LLM never decides quarantine.** No model is consulted to decide whether to deny, detect,
   taint, or quarantine — it is deterministic, always. Models are the *subject* of enforcement, never
   a participant in it.
3. **Tainted output never reaches a downstream worker**, and **the control plane fails closed** —
   unreachable AgentShield means deny, and the run reports `fail_closed: true` so a network blip is
   never mistaken for the policy.

## Quick start

WorkSwarm needs its own virtualenv (Python <3.14), and AgentShield runs on **8100** because
WorkSwarm's own server also defaults to 8000. Postgres is not required.

```bash
# One-time
cp .env.example .env                       # fill in only what you want
python3.11 -m venv .venv-workswarm
.venv-workswarm/bin/pip install workswarm==0.2.6
printf 'NEXT_PUBLIC_BACKEND_URL=http://localhost:8100\nNEXT_PUBLIC_BACKEND_WS_URL=ws://localhost:8100\n' \
  > frontend/.env.local
```

Three terminals from the repository root:

```bash
make demo-backend     # AgentShield on :8100
make demo-frontend    # frontend on :3000  →  open http://localhost:3000/demo
make demo-reset       # restores the vulnerable baseline, proves it green
AGENTSHIELD_BASE_URL=http://localhost:8100 AGENTSHIELD_DEMO_REAL_MODELS=1 \
  .venv-workswarm/bin/python workswarm/run_demo.py
```

PowerShell equivalents (`.venv*/Scripts/`) accompany every command in
[`docs/DEMO.md`](docs/DEMO.md) §2. `AGENTSHIELD_DEMO_REAL_MODELS=1` is non-negotiable for a real-model
verification: with no endpoint resolved the command exits before creating a session rather than
silently falling back to deterministic workers. Budget **4–7 minutes** (measured: 3:59 and 6:05);
~2 seconds with deterministic workers. Exit code is `0` only if the workflow reached `recovered`.

## Tech stack

| | |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn, Pydantic, WebSocket event stream, NetworkX, asyncpg/Postgres (optional) |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind v4, Sigma.js + Graphology |
| Swarm | `workswarm==0.2.6` (`openjiuwen.core.workflow` SwarmFlow), separate Python 3.11 venv |
| Models | OpenAI-compatible HTTP via `httpx`; OpenRouter verified, RunPod/vLLM optional |
| Telemetry | `sentry-sdk[fastapi]`, trace propagated across both processes; OTLP/JSON export |
| Verification | pytest, ruff, vitest, eslint, `tsc --noEmit`, `next build`; Docker Compose for Postgres |

Deliberately small: no message queue, no agent framework of our own, no vector database, no LLM
judge. Sentry, OpenRouter, RunPod, and Postgres are each individually absent-safe, asserted by
`backend/tests/test_runtime_optional_integrations.py`.

## The simulator console

A separate artifact, never conflated with the live demo: the deterministic lab AgentShield grew out
of. A typed security graph — agents, tools/MCP servers, credentials, resources, sentinels — attacked
by pluggable seeded scenarios (probabilistic propagation, an adaptive attacker that switches
targeting on the observed quarantine rate, sentinel compromise, attestation replay, Byzantine
collusion, false quarantine) and scored on containment, blast radius, and retained utility across
Overview, Topology, Activity, Metrics, Defenses, Remediation, and Runs.

![Overview — posture KPIs, outbreak progression, workflow tracker](docs/screenshots/overview.jpg)

![Topology — typed security graph with a node inspector](docs/screenshots/topology.jpg)

```bash
make dev              # docker compose: Postgres + backend :8000 + frontend :3000
make benchmark        # 14 attack presets + 7 defense postures + a remediation before/after
make golden-demo      # a simulated run: attack → adaptation → subversion → fix → re-test
make verify-determinism
```

Every run is seeded, event-sourced, persisted, and replayable; every live endpoint has a
`.../replay/...` twin reconstructing a past run's exact final state field-for-field.

## Verification

```bash
make test-demo-target   # the vulnerable app's own suite: 6 green at reset
make test-bridge        # the WorkSwarm-side bridge, with the BACKEND venv: 54 tests
cd backend && .venv/bin/pytest          # 480 passed, 21 skipped (skips are Postgres-only)
cd backend && .venv/bin/ruff check .
cd frontend && npm run lint && npx next typegen && npx tsc --noEmit && npx vitest run && npm run build
```

Frontend: 169 vitest tests, eslint clean, `tsc --noEmit` clean, `next build` clean across 13 routes.
Persistence-integration tests require a reachable Postgres and skip automatically otherwise.

---

Design inspiration is acknowledged in [`docs/BRIEF.md`](docs/BRIEF.md) — notably
[AEGIS](https://github.com/gaiarobotics/aegis) (Agent Embedding Guard & Immune System) and Michael
Barnathan's work on prompt worms in multi-agent spaces. AgentShield's contribution is the other half:
containment as an external control plane, provable event by event.
