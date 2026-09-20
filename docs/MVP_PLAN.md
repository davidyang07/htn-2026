# AgentShield — MVP Implementation Plan

> **Purpose:** the build order for the Live Swarm Demo, optimized for speed. Read
> `docs/PROJECT.md` (what) and `docs/ARCHITECTURE.md` (how) first.
>
> **Prime directive:** the entire MVP exists to make **one** demo work end to end. Finish P0 in
> order. Do not start a P1 item while a P0 item is unfinished.
>
> *(This file is deliberately exempted from the `docs/*_PLAN.md` gitignore rule — see
> `.gitignore`. It is authoritative for the pivot, unlike the older throwaway planning docs that
> rule was written for.)*

---

## Status: P0 is complete and runs end to end

Verified by running it, not by inspection (`docs/DEMO.md` has the runbook and
the measured numbers):

| Item | Status |
|---|---|
| P0.1 demo target | Done. 6 tests green at baseline; the regression test fails unpatched, passes patched. |
| P0.2 live runtime state | Done. `backend/app/runtime/session.py` + `registry.py`. |
| P0.3 deterministic policy | Done. `backend/app/runtime/policy.py`, 62 tests. |
| P0.4 runtime API + bridge | Done. 17 routes + WS; `workswarm/agentshield_client.py` fails closed. |
| P0.5 offline SwarmFlow | Done. `workswarm/flows/auth_fix_flow.py`. |
| P0.6 the real attack | Done. The injection lands; the request is document-driven, not hardcoded. |
| P0.7 quarantine | Done. Full cascade at seq 17–21 of a real run. |
| P0.8 replacement worker | Done. Trusted context only, enforced with a 409. |
| P0.9 developer patch | Done. A real edit, sandbox-bounded. |
| P0.10 real pytest | Done. Real subprocess, verbatim summary, red reported red. |
| P0.11 reviewer | Done. Verifies against evidence; `WORKFLOW_RECOVERED`. |
| P0.12 `/demo` | Done, and **verified in a real browser**, not just via `tsc`. |
| P0.13 Sentry | Done. Distributed trace across both processes; delivery confirmed HTTP 200. |
| P0.14 OpenAI explanation | Done, optional; deterministic fallback always available. |

Totals: backend **480 passed, 21 skipped**; bridge **43 passed**; demo target
**6 → 8 passed**; frontend **169 vitest**, eslint / `tsc --noEmit` / `next
build` clean.

### Deviations from this plan, and why

1. **`demo_target/docs/auth_notes.md`, not `authentication.md`.** The file name
   the implementation brief specified. Nothing else changed.
2. **`backend/app/runtime/resources.py` is a fifth module**, not folded into
   `session.py`. It is the *fetch* half of the enforcement point and it
   re-checks the policy before touching the filesystem; keeping it separate is
   what lets `test_runtime_resources.py` prove a protected path cannot be read
   even by a caller inside AgentShield that forgot to check.
3. **Explicit lifecycle routes instead of one `POST .../events` ingest.** A
   generic ingest would let a caller assert a security outcome. Each route is
   one concrete capability, and `reassign` *validates* the replacement's seed
   context rather than recording whatever it is told.
4. **`GET .../snapshot` was added.** Without it, opening `/demo` after a run
   shows an empty timeline and four unlit verdict lights — the socket's
   snapshot carries node state but no history. See ARCHITECTURE §7.3.
5. **Deterministic worker stand-ins exist** for the no-model configuration,
   and are labelled as such everywhere. See §P0.5 below.
6. **`workswarm/reset_demo.py` replaces `git clean -fd demo_target/`** in the
   reset procedure. While `demo_target/` is untracked, `git clean -fd` deletes
   it outright instead of resetting it.
7. **The port moved to 8100 per-run, not in code.** Changing the code default
   would break `make types` and CI's `schema-drift` job for no demo benefit.

---

## Baseline verified before this plan was written

- Backend: **354 passed, 21 skipped** (skips are Postgres-only tests; no local Postgres/Docker).
  `ruff check .` clean.
- Frontend: **159/159 vitest**, `eslint` clean, `next typegen` + `tsc --noEmit` clean,
  `next build` succeeds (12 routes).
- No pre-existing code failures. See the final section for the environment caveats.

---

## Ground rules for every P0 item

1. **One attack, one policy, one quarantine flow, one recovery flow, one demo app, one UI screen.**
   Nothing else.
2. **The quarantine decision stays deterministic.** No model input, ever.
3. **Never read a protected resource before the policy decision returns.**
4. **Fail closed.** An unreachable AgentShield API is a denial, not an allow.
5. **Do not modify the simulator, replay, persistence, or the existing frontend screens.**
6. **Do not weaken or skip an existing test.**
7. Any new route / response model / `EventType` member ⇒ run `make types` and commit the
   regenerated `frontend/src/lib/api/schema.d.ts`, or CI's `schema-drift` job fails.
8. Run `backend/.venv/bin/pytest`, `ruff check .`, and the frontend chain before claiming an item
   done.

---

# P0 — the critical path

## P0.1 — Tiny vulnerable `demo_target`

The thing the swarm actually fixes. Must contain a *real* bug with a *real* failing test, because
the Developer writes a real patch and a real `pytest` run verifies it.

**Create**

| Path | Purpose |
|---|---|
| `demo_target/README.md` | Benign project overview |
| `demo_target/app/auth.py` | The authentication module with one genuine vulnerability |
| `demo_target/app/__init__.py` | Package marker |
| `demo_target/tests/test_auth.py` | Existing passing tests (so a green baseline exists) |
| `demo_target/docs/auth_notes.md` | **The poisoned document** — see P0.6 |
| `demo_target/secrets/demo_secret.txt` | A fabricated synthetic secret, never read by anything |
| `demo_target/secrets/README.md` | States plainly that this is synthetic and protected |
| `demo_target/pytest.ini` or `pyproject.toml` | So `pytest demo_target` runs standalone |

**The vulnerability.** Pick something small, real, and obviously wrong once pointed at — e.g. a
token/password comparison using `==` instead of `hmac.compare_digest` (timing-unsafe), or a session
check that accepts an expired token. It must be:

- fixable in a handful of lines by an LLM Developer worker,
- provable by a regression test that fails before the patch and passes after,
- unrelated to the injection, so the attack and the task are genuinely independent.

**Verify:** `pytest demo_target` is green at baseline; the intended regression test fails against
the unpatched code.

**Constraint:** the secret file contains a fabricated string only. It is not a credential to
anything. Write it as obviously synthetic (e.g. `DEMO-SYNTHETIC-SECRET-DO-NOT-USE-...`).

---

## P0.2 — Live AgentShield runtime state

**Create**

| Path | Contents |
|---|---|
| `backend/app/runtime/__init__.py` | *(scaffolded in this pass)* |
| `backend/app/runtime/session.py` | `WorkerNode`, `Artifact`, `LiveRuntimeSession` |
| `backend/app/runtime/registry.py` | `RuntimeRegistry` — `dict[UUID, LiveRuntimeSession]` |

`LiveRuntimeSession` owns one `EventBus` and one `EventEmitter` (both imported unchanged from
`app/events/`), a `dict[str, WorkerNode]` keyed by worker id, and a `dict[str, Artifact]`.
`WorkerNode.security_state` is the **existing** `app/engine/state.py::SecurityState`.

Methods: `register_worker`, `quarantine`, `record_artifact`, `taint_artifacts_of`,
`trusted_context_for`, `snapshot()` (returning the existing `SnapshotFrame`), `summary()`.

**Do not** put this in `app/engine/` — it does I/O and holds mutable session state, which the
engine's purity contract forbids (`docs/SPEC.md` §1 decision 2). `app/agents/runtime.py` already
sits outside the engine for the same reason.

**Test:** `backend/tests/test_runtime_session.py` — register, quarantine, taint, snapshot shape,
monotonic `seq`.

---

## P0.3 — Deterministic `secrets/**` policy

**Create:** `backend/app/runtime/policy.py` — a pure, total `evaluate(resource_path) -> Decision`.

**Must deny:** anything normalizing under `demo_target/secrets/`, including `./`-prefixed,
backslash-separated, `..`-containing, and double-separator variants; anything resolving outside the
`demo_target/` sandbox root; anything unparseable.

**Must allow:** ordinary paths inside `demo_target/` (`app/auth.py`, `docs/auth_notes.md`,
`README.md`, `tests/test_auth.py`).

**Test:** `backend/tests/test_runtime_policy.py` — a table of traversal and separator variants. This
is the cheapest test in the project and the most expensive one to have skipped. Write it first.

---

## P0.4 — WorkSwarm HTTP/event bridge

**Create**

| Path | Contents |
|---|---|
| `backend/app/schemas/runtime.py` | `SessionCreateRequest`, `WorkerSpec`, `ResourceRequest`, `ResourceDecision`, `RuntimeEventRequest`, `RuntimeSessionSummary` |
| `backend/app/api/routes_runtime.py` | The router below, plus the WS route |
| `workswarm/__init__.py` | *(scaffolded in this pass)* |
| `workswarm/agentshield_client.py` | The client the SwarmFlow calls |

**Modify**

| Path | Change |
|---|---|
| `backend/app/main.py` | `app.include_router(routes_runtime.router)` — one line |
| `backend/app/schemas/events.py` | +4 additive `EventType` members (§7.2 of ARCHITECTURE) |
| `frontend/src/lib/vocabulary.ts` | Human labels for the 4 new event types |
| `frontend/src/lib/api/schema.d.ts` | **Regenerated** via `make types` |

**Routes**

```
POST /api/runtime/sessions                        201 -> RuntimeSessionSummary
POST /api/runtime/sessions/{id}/resource-request  200 -> ResourceDecision
POST /api/runtime/sessions/{id}/events            202
GET  /api/runtime/sessions/{id}                   200 -> RuntimeSessionSummary
WS   /api/runtime/sessions/{id}/stream            snapshot + deltas
```

`resource-request` is a **synchronous decision endpoint**. Its response body
(`decision`, `reason`, `quarantined`, `recovery_required`, optional `content`) is what the workflow
obeys. Emit the full deny cascade (`TOOL_REQUESTED` → `TOOL_DENIED` → `POLICY_VIOLATION` →
`ANOMALY_DETECTED` → `AGENT_QUARANTINED`) inside the handler, before responding.

The WS route mirrors `app/api/ws.py` structurally — **preserve its subscribe-before-snapshot
ordering exactly**; that discipline is load-bearing and easy to break by rearranging.

`agentshield_client.py` **fails closed**: a timeout, connection error, or non-2xx response is
treated as a denial.

**Test:** `backend/tests/test_routes_runtime.py` (FastAPI `TestClient`, the existing convention) —
create, allowed request, denied request + full event cascade, WS snapshot-then-delta.

---

## P0.5 — Offline SwarmFlow

**Create**

| Path | Contents |
|---|---|
| `workswarm/README.md` | Local setup: install WorkSwarm, configure the sponsor model, run the flow |
| `workswarm/flows/auth_fix_flow.py` | The offline-authored SwarmFlow |
| `workswarm/flows/__init__.py` | Package marker |
| `workswarm/prompts/*.md` or `.py` | Per-worker system prompts |
| `workswarm/run_demo.py` | The single command that runs the demo |

Workers: Repo Analyst, Security Researcher, Developer, Reviewer, plus the Replacement Researcher
path. (No separate Leader *component*: the authored graph itself is the decomposition, which is
what "offline-authored" means — a Leader node would be a dynamic planner improvising on stage.)

**The critical contract:** the Security Researcher has **no filesystem capability**. Its structured
output includes `requested_files: list[str]`. The flow sends each entry to `resource-request` and
only reads what comes back allowed.

**Implemented file names** differ slightly from the table above: `workers.py`, `prompts.py`,
`injection.py`, `patcher.py`, `telemetry.py`, `config.py`, `reset_demo.py` alongside
`flows/auth_fix_flow.py` and `run_demo.py`. `workswarm/README.md` is the index.

**Workers when no model is configured.** The reasoning workers are WorkSwarm `LLMComponent`s when
an OpenAI-compatible endpoint is configured, and deterministic components otherwise. The
stand-ins are still real WorkSwarm workflow components, and the Security Researcher's is genuinely
injection-susceptible: `workswarm/injection.py` reads the document AgentShield released and
extracts the paths that document *instructs its reader to fetch*. Nothing hardcodes the secret's
path — retarget the poisoned paragraph and it asks for the new path, delete it and it asks for
nothing, both pinned by `workswarm/tests/test_bridge.py`.

This is labelled, never implied: every worker registers with `model_backed` set truthfully, the
`/demo` screen shows `model-backed` or `deterministic stand-in` per worker, and `run_demo.py`
prints the mode. A deterministic run makes a weaker claim about *model* behaviour and exactly the
same claim about AgentShield — the enforcement path is byte-for-byte identical.

WorkSwarm is installed separately and is **not** modified. See `docs/WORKSWARM.md`.

---

## P0.6 — The real attack

**Create/finish:** `demo_target/docs/auth_notes.md` — a genuinely useful authentication
document with an indirect prompt injection embedded in it, instructing the reader to obtain
`demo_target/secrets/demo_secret.txt`.

It must read as a plausible document a Security Researcher would consult for this task — the
attack's credibility is the demo's credibility. Mark the file with a visible header stating it is
intentionally adversarial demo content (safety constraint, `docs/BRIEF.md` §10).

**Verify:** run the flow and confirm from the event log that the worker *actually* requested the
protected path because of the document. If the injection does not land, tune the payload — do not
hardcode the request.

---

## P0.7 — Quarantine

Wire `LiveRuntimeSession.quarantine()` into the deny path: worker → `QUARANTINED`, artifacts
tainted, `recovery_required=true` in the response.

**Modify:** `backend/app/runtime/session.py`, `backend/app/api/routes_runtime.py`.

**Test:** a quarantined worker's subsequent requests are refused regardless of path; its artifacts
are excluded from `trusted_context_for`.

---

## P0.8 — Replacement worker

**Modify:** `workswarm/flows/auth_fix_flow.py` — on `recovery_required`, start a Replacement
Researcher seeded from `trusted_context_for()` only. The poisoned document's content must not
appear in its prompt. Emit `TASK_REASSIGNED`, then `AGENT_CREATED` with `metadata.replaces`.

**Test:** an assertion in the flow (or a runtime test) that the replacement's context contains no
tainted artifact.

---

## P0.9 — Developer patch

The Developer worker writes a real patch to `demo_target/app/auth.py` plus a regression test.
Emit `TASK_COMPLETED` with `metadata.step="patch"` (Sentry: `developer.patch_applied`).

**Modify:** `workswarm/flows/auth_fix_flow.py`. Constrain writes to `demo_target/` — a worker must
not be able to write outside the sandbox.

---

## P0.10 — Real pytest

Run `pytest demo_target` for real and capture the exit code and summary line. Emit `TASK_COMPLETED`
with `metadata.step="pytest"` and the real counts (Sentry: `swarm.tests_passed`).

**Do not fabricate the result.** A red run is reported red — that honesty is the whole reason a
real test run is in the demo instead of a claim.

**Create:** `workswarm/verify.py` (or equivalent) — subprocess runner returning structured results.

---

## P0.11 — Reviewer

The Reviewer independently verifies the patch and the test evidence, then the flow emits
`WORKFLOW_RECOVERED` (Sentry: `swarm.recovery_complete`) and `TASK_COMPLETED` with
`metadata.step="review"`.

**Modify:** `workswarm/flows/auth_fix_flow.py`, plus prompts.

---

## P0.12 — `/demo` frontend

**Create**

| Path | Contents |
|---|---|
| `frontend/src/app/demo/page.tsx` | *(minimal placeholder scaffolded in this pass)* — the full screen |
| `frontend/src/lib/runtime/useRuntimeStream.ts` | Mirrors `useExperimentStream`, incl. `seq`-gap desync handling |
| `frontend/src/lib/runtime/client.ts` | `runtimeWsUrl()` + session fetches |

**Modify**

| Path | Change |
|---|---|
| `frontend/src/components/shell/nav.ts` | Add the `/demo` nav entry |
| `frontend/src/lib/vocabulary.ts` | Labels for the new event types |

Reuse `reduce()` from `lib/stream/reducer.ts` unchanged, plus `Panel`/`PanelHeader`/`PageHeader`/
`Badge`, the `EventFeed`/`EventRow` components, and `TopologyGraph`.

The screen should read as a narrative, not a dashboard: the swarm graph with live worker states,
the event timeline, and a verdict strip —

```
ATTACK DETECTED   AGENT QUARANTINED   WORKFLOW RECOVERED   TESTS PASSED
```

Respect the design system: colour means severity/security state only; the accent is interaction
only (`docs/PLAN.md` §12).

**Verify in a real browser**, not just via `tsc`. The existing `/topology` screen was the one piece
several prior sessions could not verify blind, and it stayed broken until someone actually looked.

---

## P0.13 — Sentry tracing and logging

**Not to be started before P0.12 is working.**

**Create:** `backend/app/telemetry/sentry.py` — init guarded on `SENTRY_DSN`; a no-op when absent.

**Modify:** `backend/app/main.py` (init at startup), `backend/app/api/routes_runtime.py` (spans +
structured logs), `workswarm/flows/auth_fix_flow.py` (workflow-side spans), `backend/pyproject.toml`
(`sentry-sdk`), `.env.example` (already has `SENTRY_DSN=`).

Spans: whole swarm run → each worker → each policy check → quarantine → reassignment → patch →
pytest → reviewer.

Logs: `security.policy_violation`, `security.tool_denied`, `security.agent_quarantined`,
`swarm.task_reassigned`, `swarm.replacement_started`, `developer.patch_applied`,
`swarm.tests_passed`, `swarm.recovery_complete`.

**Hard requirement:** with no DSN, the app behaves identically. Add a test asserting that.

Note the existing hand-built OTLP/JSON exporter (`app/telemetry/otel_export.py`) already covers the
simulator — this is additive and separate.

**When a real Sentry observation drives a real fix, record it in `docs/CODEX_DEVLOG.md`.**

---

## P0.14 — Optional post-hoc incident explanation

**Implemented:** `backend/app/explanation/` projects the *already-recorded* incident into a frozen,
extra-forbidden evidence allowlist and returns five-part developer-facing commentary. It reuses the
WorkSwarm/OpenRouter provider configuration when available and otherwise returns deterministic
local text.

**Endpoint:** `GET /api/runtime/sessions/{id}/explanation` returns the safe evidence, explicit
answers to the five incident/recovery questions, a source label, provider/model identity when an
AI wrote it, and an authority disclaimer. The provider sees the evidence JSON only. Plain `httpx`
remains the only client dependency.

**Absolute constraint:** runs strictly *after* `POLICY_VIOLATION` and `AGENT_QUARANTINED` are
emitted. Never an input to allow, deny, quarantine, trust, replacement, or workflow completion.
Absent, unreachable, timed-out, HTTP-error, or malformed providers all produce the deterministic
fallback; nothing in the core demo changes.

---

# P1 — after the demo works end to end

- **RunPod replacement worker — Done.** `RUNPOD_MODEL_*` is replacement-only, verified before
  selection, and records the provider that actually answered. Missing, unhealthy, timed-out, or
  unreachable endpoints fall back to the normal sponsor route and never block the P0 workflow.
- **AgentShield as a visible third-party Sentinel agent in the swarm graph** — if trivial. The
  typed graph already has `NodeType.SENTINEL` with its own shape and size in
  `lib/graph/model.ts::NODE_SHAPE`.
- **Richer artifact tainting** — transitive taint across the artifact dependency graph rather than
  per-worker.
- **Before/after replay polish** — run the same flow with enforcement disabled to show the secret
  being reached, then enabled. This is the strongest possible proof and reuses the existing
  before/after-defense-comparison framing.
- **Durable live-session persistence** — a new table or an adapter making `PostgresWriter` work
  for live sessions. Deliberately excluded from P0 (`docs/ARCHITECTURE.md` §8).

# P2 — not before the hackathon demo is locked

- More attack families (credential abuse, tool poisoning, collusion, exfiltration variants).
- Generic integrations (MCP, LangGraph runtime, other frameworks).
- Advanced automated remediation (policy synthesis from observed incidents).

---

## Environment notes for the next pass

- No local Postgres or Docker daemon was available. 21 persistence/history/migration tests skip
  cleanly (`backend/tests/conftest.py` handles this by design). CI covers them on every push via a
  real Postgres service container. The live runtime does not need Postgres in P0.
- `pytest`'s default `tmp_path` base under `%TEMP%` was not writable in this sandbox — 7 tests in
  `tests/test_external_topology_importer.py` errored on that alone. They pass with
  `--basetemp=<writable dir>`. Purely environmental; nothing in the repo is wrong.
- The backend venv was created with Python 3.12.13 (matching CI). The machine's default Python is
  3.14.
- `docs/PLAN.md` §11 lists this project's canonical dev environment as Linux/WSL. Windows works for
  tests and build; prefer WSL for the WorkSwarm side if anything fights you.
