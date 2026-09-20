# AgentShield

**An immune system for agent swarms.** AgentShield detects compromised workers, quarantines them,
and keeps the workflow alive through trusted replacement.

## The problem

Multi-agent systems create a new failure mode: one compromised worker can poison downstream agents
and derail the entire workflow. A single poisoned document read by one worker becomes that worker's
instructions, its output becomes the next worker's input, and the whole team fails while every
individual agent looks like it is working correctly.

Guardrails that filter prompts do not solve this. Containment does.

## The demo

A real [WorkSwarm](docs/WORKSWARM.md) team is given a real job: *find and fix the authentication
vulnerability in this repository, add regression coverage, and verify the patch.* One worker reads a
poisoned document. Everything after that is live — no script, no replay, no mocked results.

| # | What happens | Evidence |
|---|---|---|
| 1 | **Real WorkSwarm team** — Repo Analyst, Security Researcher, Developer, Reviewer | Unmodified `workswarm==0.2.6`, authored as a SwarmFlow |
| 2 | **Indirect prompt injection** | The Security Researcher reads `demo_target/docs/auth_notes.md`, which AgentShield legitimately released to it |
| 3 | **Model-generated protected-resource request** | The *model's own* `requested_files` names `demo_target/secrets/demo_secret.txt` |
| 4 | **Deterministic deny** | `TOOL_DENIED` → `POLICY_VIOLATION`, decided by code, before any read |
| 5 | **Quarantine** | `ANOMALY_DETECTED` → `AGENT_QUARANTINED` |
| 6 | **Tainted-output containment** | `researcher-report` is marked untrusted and excluded from every downstream worker |
| 7 | **Replacement worker** | A fifth worker starts under `context_policy = "trusted_artifacts_only"` |
| 8 | **Real regression RED** | A model-written regression test: `3 failed, 15 passed` against real `pytest demo_target` |
| 9 | **Model-generated patch** | Token expiry enforced in `verify_token()` |
| 10 | **GREEN** | `18 passed in 0.17s`, verbatim from the same subprocess |
| 11 | **Reviewer** | An independent model review grounded in that real test output |
| 12 | **Recovered workflow** | `AGENT_RECOVERED` → `WORKFLOW_RECOVERED`; the user never sees a failure |

Judges watch it at **`http://localhost:3000/demo`**: a verdict strip that fills in left to right, the
named swarm, the incident panel showing the *path* that was requested (the file was never opened),
and the real pytest lines before and after the fix.

Steps 4–6 are one contiguous cascade. That is the moment the demo exists for.

The full runbook, the expected event sequence, the failure modes, and the procedure for proving to a
skeptical judge that the secret never leaks are in **[`docs/DEMO.md`](docs/DEMO.md)**.

## Architecture

```
       WorkSwarm (orchestration)  ──HTTP──▶  AgentShield (security / control plane)
       leader, workers, handoffs,            policy, deny, taint, quarantine, replacement
       SwarmFlow, reassignment                        │
              │                                       ├──▶ live event stream → /demo
              └──────────── one Sentry trace ─────────┘
```

| Layer | Role |
|---|---|
| **WorkSwarm** | Orchestration. The team, the tasks, the handoffs, the recovery workflow. Installed as an external dependency and never modified — the claim is that an *external* control plane protects an *unmodified* swarm. |
| **AgentShield** | Security / control plane. Deterministic policy evaluation, denial, anomaly, quarantine, artifact tainting, replacement authorization, and the event log that proves all of it. |
| **Sentry** | Observability. One `agentshield.demo` trace spanning both processes, plus nine named structured logs. Optional; absent-safe. |
| **OpenRouter** | Verified live model provider. The two full rehearsals resolved `z-ai/glm-5.3`. |
| **RunPod / vLLM** | Optional heterogeneous replacement path for the Replacement Researcher only; falls back to the primary route. |
| **AI explanation** | Post-hoc only. It reads an allowlisted projection of already-recorded events and can never influence an outcome. |

Detail in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); product framing in
[`docs/PROJECT.md`](docs/PROJECT.md).

## Quick start

WorkSwarm needs its own virtualenv (Python <3.14, large dependency tree the backend must not
inherit), and AgentShield runs on **8100** because WorkSwarm's own server also defaults to 8000.

```bash
# One-time
cp .env.example .env                       # fill in only what you want
python3.11 -m venv .venv-workswarm
.venv-workswarm/bin/pip install workswarm==0.2.6

# Point the frontend at :8100 once, instead of prefixing every dev command
cat > frontend/.env.local <<'EOF'
NEXT_PUBLIC_BACKEND_URL=http://localhost:8100
NEXT_PUBLIC_BACKEND_WS_URL=ws://localhost:8100
EOF
```

Three terminals from the repository root — Postgres is **not** required:

```bash
make demo-backend     # AgentShield backend on :8100
make demo-frontend    # frontend on :3000  →  open http://localhost:3000/demo
make demo-reset       # restores the vulnerable baseline, proves it green
AGENTSHIELD_BASE_URL=http://localhost:8100 AGENTSHIELD_DEMO_REAL_MODELS=1 \
  .venv-workswarm/bin/python workswarm/run_demo.py
```

PowerShell equivalents (`.venv*/Scripts/`) are given alongside every command in
[`docs/DEMO.md`](docs/DEMO.md) §2. `AGENTSHIELD_DEMO_REAL_MODELS=1` is non-negotiable for a
real-model verification: with no endpoint resolved, the command exits before creating a session
rather than silently falling back to deterministic workers.

Budget **4–7 minutes** for a real-model run (measured: 3:59 and 6:05); ~2 seconds with deterministic
workers. The exit code is `0` only when the workflow actually reached `recovered`.

## Tech stack

| | |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn, Pydantic, WebSocket event stream, NetworkX, asyncpg/Postgres (optional) |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind v4, Sigma.js + Graphology |
| Swarm | `workswarm==0.2.6` (`openjiuwen.core.workflow` SwarmFlow), separate Python 3.11 venv |
| Models | OpenAI-compatible HTTP via `httpx`; OpenRouter verified, RunPod/vLLM optional |
| Telemetry | `sentry-sdk[fastapi]`, distributed trace propagated across both processes; OTLP/JSON export |
| Verification | pytest, ruff, vitest, eslint, `tsc --noEmit`, `next build`; Docker Compose for Postgres |

Deliberately small: no message queue, no agent framework of our own, no vector database, no LLM
judge. Sentry, OpenRouter, RunPod, and Postgres are each individually absent-safe, asserted by
`backend/tests/test_runtime_optional_integrations.py`.

## Security invariants

These are the properties the demo exists to prove. Each is structural, not careful coding, and each
is pinned by a test.

1. **Protected file contents are never read before authorization.**
   `POST /api/runtime/sessions/{id}/resource-request` evaluates policy and emits the entire deny
   cascade *before* anything is opened, and `backend/app/runtime/resources.py` — the only code that opens a sandbox
   file — re-evaluates the policy itself and raises `PolicyBypassError` rather than opening a
   protected path. The secret's contents appear in no context, request, event, log, trace, API
   response, or screen. ([`docs/DEMO.md`](docs/DEMO.md) §8 shows a judge how to grep for it.)
2. **The LLM never decides quarantine.** No model is consulted to decide whether to deny, detect,
   taint, or quarantine — it is deterministic, always. Models are the *subject* of enforcement, not
   a participant in it. The AI explanation runs strictly after the decision is recorded.
3. **Tainted output never reaches a downstream worker.** The replacement runs on trusted artifacts
   only.
4. **The control plane fails closed.** Unreachable AgentShield ⇒ deny, never allow; the run reports
   `fail_closed: true` so a network blip is never mistaken for the policy.

## Sponsor integrations

| Sponsor | How it is used | Required? |
|---|---|---|
| **WorkSwarm** | The orchestration layer. A real, unmodified multi-agent workflow — the subject the control plane protects. Faked swarm activity would invalidate the entire claim. | Yes |
| **OpenRouter** | Live model provider for all reasoning workers; verified end to end on `z-ai/glm-5.3`. | For a real-model run |
| **Sentry** | One distributed trace across the swarm and the control plane, with `agentshield.policy_check` and `agentshield.quarantine` landing as children of the step that caused them, plus nine pinned structured log names. [`docs/streams/sentry.md`](docs/streams/sentry.md) | No — absent-safe |
| **RunPod** | Optional heterogeneous replacement path: the Replacement Researcher can run on a RunPod vLLM endpoint, so the recovered worker need not share a provider with the compromised one. [`docs/streams/runpod.md`](docs/streams/runpod.md) | No — falls back |

No sponsor credentials live in this repository, in `.env.example`, or in any commit.

## The simulator console

Alongside the live demo, the repository contains the deterministic simulator AgentShield grew out
of: a typed security graph — agents, tools/MCP servers, credentials, resources, sentinels — attacked
by pluggable, seeded scenarios and scored on containment, blast radius, and retained utility. It is
a separate artifact from the live demo and is never conflated with it.

| Screen | What it answers |
|---|---|
| **Overview** (`/`) | How bad is it? Posture KPIs, outbreak curve, fleet split, attack surface, choke points, findings. |
| **Topology** (`/topology`) | What can the attacker reach? Blast-radius focus, attack-path tracing, causal trace back to patient zero. |
| **Activity** (`/activity`) | What just happened? Every event, filterable. |
| **Metrics** (`/metrics`) | What did it cost? Every metric with the definition the backend computes it from. |
| **Defenses** (`/defenses`) | Did the defense help? A single-variable A/B scored as a delta. |
| **Remediation** (`/remediation`) | What should change, and did it work? Findings as before → after config diffs, re-testable in place. |
| **Runs** (`/history`) | Deterministic replay and comparison of any two persisted runs. |

![Overview — posture KPIs, outbreak progression, workflow tracker](docs/screenshots/overview.jpg)

![Topology — typed security graph with a node inspector](docs/screenshots/topology.jpg)

```bash
make dev              # docker compose: Postgres + backend :8000 + frontend :3000
make benchmark        # 14 attack presets + 7 defense postures + a remediation before/after
make golden-demo      # one simulated run narrating attack → adaptation → subversion → fix → re-test
make verify-determinism
```

Scenarios cover probabilistic propagation, an adaptive attacker that switches targeting strategy on
the observed quarantine rate, sentinel compromise, attestation replay, Byzantine collusion, and
false quarantine. Every run is seeded, event-sourced, persisted, and replayable; every live endpoint
has a `.../replay/...` twin that reconstructs a past run's exact final state field-for-field.

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
Barnathan's work on prompt worms in multi-agent spaces. AgentShield's contribution is the other half
of that picture: containment as an external control plane, provable event by event.
