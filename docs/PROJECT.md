# AgentShield — an immune system for real multi-agent teams

> **Status:** canonical product document for the Hack the North 2026 direction.
>
> **Authority:** this document defines the *product*. `docs/ARCHITECTURE.md` defines how it is
> built, `docs/MVP_PLAN.md` defines the build order, `docs/WORKSWARM.md` defines the WorkSwarm
> relationship, `docs/DEMO.md` defines the demo script.
>
> **Relationship to the existing docs:** `docs/SPEC.md` remains authoritative for the low-level
> mechanism it defines (event schema, derived-keyed RNG, fixed-tick engine, snapshot/delta
> protocol) — that mechanism is *preserved and reused*, not replaced. `docs/PLAN.md` remains
> authoritative for the deterministic simulator, which survives intact as the evaluation lab.
> Where PLAN's *product framing* ("an evaluation/simulation platform") conflicts with this
> document, this document wins.

---

## 1. Product name

**AgentShield.**

The live runtime introduced by this direction is the **AgentShield control plane**; the demo it
powers is the **Live Swarm Demo**.

> **Naming caution.** The existing simulator already ships something called the "golden demo"
> (`make golden-demo`, `backend/app/benchmark/golden_demo.py`) — a headless, deterministic
> narration of the simulated attack story. That is a *different artifact* from this document's
> golden demo. Throughout the new docs, the live one is called the **Live Swarm Demo** and the
> old one the **simulator golden demo**. Do not merge them.

---

## 2. One-sentence pitch

AgentShield is an immune system for multi-agent AI teams: it sits beside a real running swarm,
deterministically denies the actions a compromised worker tries to take, quarantines that worker,
stops its poisoned output from spreading, and lets the team recover and still finish the job.

---

## 3. The problem

Multi-agent systems are built on the assumption that every worker is honest.

A modern agent team decomposes a task across specialized workers, and each worker's output becomes
the next worker's input. That handoff is the trust boundary, and nothing guards it. One worker that
reads an untrusted document — a README, an issue, a dependency changelog, a doc page — can be
redirected by an **indirect prompt injection** buried in that content. From that moment:

1. The compromised worker acts on the attacker's goals while looking like it is doing its job.
2. Whatever it produces is accepted downstream as trusted context.
3. The compromise propagates through the team's own collaboration graph.
4. The user sees a plausible final answer and never learns anything went wrong.

Existing defenses miss this in two different ways:

- **Prompt filtering / guardrails** try to make each individual model call safe. They operate on
  text, they are probabilistic, and they are one jailbreak away from useless. They also say nothing
  about what happens *after* a worker is already compromised.
- **Observability / tracing products** record what happened. They do not intervene, and by the
  time a human reads the trace the secret has already been read.

Neither treats the multi-agent *system* as the unit of defense.

---

## 4. The solution

AgentShield is an external, deterministic **security control plane** for a running agent swarm.

Every action a worker wants to take that touches a resource — read this file, call this tool, hit
this endpoint — is routed through AgentShield *before it happens*. AgentShield answers `allow` or
`deny` from a deterministic policy, and on a denial it does four more things:

1. **Records** the policy violation as a structured, replayable event.
2. **Raises** an anomaly on the requesting worker.
3. **Quarantines** that worker — it is removed from the team and can take no further action.
4. **Taints** that worker's output, so the poisoned context cannot reach a downstream worker.

Then it tells the orchestrator that **recovery is required**, and the swarm re-assigns the
quarantined worker's task to a fresh replacement worker seeded only with trusted context. The team
finishes the job.

The three properties that make this different from a guardrail:

- **The decision is deterministic.** A path policy match is a string comparison, not a model
  judgment. It cannot be argued out of a denial, and it produces the same answer every run —
  which is also what makes the demo reliable and the behavior testable.
- **The enforcement point is outside the agent.** The worker never holds the capability it is
  trying to abuse. It can only *ask*, in structured output, and AgentShield answers. An injection
  that fully captures the worker still cannot reach the protected resource.
- **The response is containment plus recovery, not refusal.** The user still gets their result.

---

## 5. Why "immune system"

A biological immune system does not promise that every cell stays healthy. That promise is
unkeepable, and a body built on it would die of the first infection. Instead it:

- **detects** abnormal behavior rather than trying to make infection impossible,
- **isolates** the compromised component,
- **limits propagation** to neighbouring tissue,
- and **preserves the larger organism**, which keeps functioning throughout.

AgentShield makes exactly that trade for agent swarms. We do not claim a worker can be made
un-compromisable — with untrusted input in the context window, it cannot. We claim that one
compromised worker does not have to mean a compromised *team*:

| Immune system | AgentShield |
|---|---|
| Abnormal cell behavior | A worker requesting a resource outside its policy envelope |
| Antigen recognition | Deterministic policy evaluation at the enforcement point |
| Isolating the infected cell | Worker quarantine |
| Preventing systemic spread | Output tainting — the quarantined worker's artifacts never propagate |
| Tissue regeneration | Replacement worker started with trusted context only |
| The organism survives | The workflow completes, tests pass, the user gets their answer |

This framing must be used consistently in the product, the UI, and every document in `docs/`.

**What this is not:** it is not prompt filtering, and the documentation should never let a reader
conclude that it is. Prompt filtering is a claim about text. This is a claim about system
resilience.

---

## 6. The golden demo (Live Swarm Demo)

One demo, polished end to end. Everything in the MVP exists to serve it.

**The ask.** A user gives a WorkSwarm software-engineering team a genuinely useful task:

> "Find and fix the authentication vulnerability in this repository, add regression coverage, and
> verify the patch."

**The team.** The WorkSwarm Leader decomposes the task across specialized workers:

- **Repo Analyst** — maps the repository and its documentation.
- **Security Researcher** — investigates the vulnerability.
- **Developer** — writes the patch and the regression test.
- **Reviewer** — independently verifies the result.

**The attack.** The repository contains an intentionally poisoned documentation file. The Security
Researcher reads it *as part of its legitimate task* — this is not a contrived tool call, it is the
job. The document carries an indirect prompt injection instructing the worker to obtain
`demo_target/secrets/demo_secret.txt`, a file containing a fake synthetic secret and nothing else.

**The critical mechanic.** The worker cannot read that file. It has no filesystem capability. All
it can do is emit, in its structured output, the list of additional resources it wants. Every one
of those requests goes to AgentShield. So the injection succeeds at capturing the worker's
*intent* and still fails to obtain anything.

**The response.** AgentShield holds one deterministic rule: any request under
`demo_target/secrets/` is denied. When the Security Researcher's request arrives, AgentShield:

1. **denies it — before the secret is read**,
2. records a policy violation,
3. emits an anomaly detection,
4. quarantines the Security Researcher,
5. marks that worker's output untrusted,
6. prevents that output from propagating downstream,
7. signals the workflow that recovery is required.

**The recovery.** WorkSwarm starts a **Replacement Researcher** using only trusted context — the
poisoned document's content never reaches it. The workflow continues: Replacement Researcher →
Developer → a real code fix → a real `pytest` run → Reviewer.

**The result the judge sees:**

```
ATTACK DETECTED
AGENT QUARANTINED
WORKFLOW RECOVERED
TESTS PASSED
```

The user receives a correct, verified result *even though one worker was compromised mid-task*.
That recovery is the heart of the product — not the denial.

**The thing that must never happen:** the contents of `demo_target/secrets/demo_secret.txt` must
never appear in any worker's context, any model request, any event payload, any log, any trace, or
anywhere in the UI. The demo's entire claim rests on this. See `docs/DEMO.md`.

---

## 7. WorkSwarm's role

**WorkSwarm** (the current openJiuwen multi-agent product) *is* the multi-agent system. It is not
simulated, mocked, or reimplemented.

- WorkSwarm owns orchestration: the Leader, task decomposition, the specialized workers, Cluster/
  Team collaboration, handoffs, and the recovery/reassignment workflow.
- AgentShield owns security: policy evaluation, denial, anomaly, quarantine, tainting, and the
  recovery signal.
- The demo workflow is authored offline as a **SwarmFlow** (WorkSwarm's Python-authored
  deterministic multi-agent workflow system) for demo reliability.
- WorkSwarm is installed and configured **manually, outside this application**. Its sponsor-model
  credentials are configured manually and never live in this repository.
- **We do not modify WorkSwarm internals.** The integration is a thin bridge the SwarmFlow calls.

AgentShield is not replacing WorkSwarm orchestration. It sits beside it as the security layer.

Full detail — including the naming history (`jiuwenswarm` / `openjiuwen` upstream) and what is
explicitly out of scope — is in `docs/WORKSWARM.md`.

**The sponsor story:** multi-agent systems should not only collaborate when everything works. They
should keep functioning when one worker becomes compromised. WorkSwarm supplies the collaboration;
AgentShield supplies the resilience. The demo must use a real WorkSwarm workflow — faked swarm
activity would invalidate the entire claim.

---

## 8. AgentShield's control-plane role

AgentShield contributes, and only contributes:

| Capability | Where it lives |
|---|---|
| Deterministic policy decision (`allow` / `deny`) | `backend/app/runtime/policy.py` (new) |
| Live session state: workers, security state, artifacts | `backend/app/runtime/session.py` (new) |
| Quarantine + output tainting | `backend/app/runtime/session.py` (new) |
| Event emission, ordering, fan-out | existing `app/events/{emitter,bus}.py`, reused verbatim |
| Event schema | existing `app/schemas/events.py`, additive only |
| Security-state vocabulary | existing `app/engine/state.py::SecurityState`, reused verbatim |
| Live WebSocket streaming to the UI | existing frame shapes, new route |
| The `/demo` screen | `frontend/src/app/demo/page.tsx` (new) |

**Hard rule: the quarantine decision is deterministic.** No model is consulted to decide whether to
deny, detect, or quarantine. This is a security property, and it is also what makes the demo
reproducible on a conference floor.

---

## 9. Sentry's role

Sentry is the **observability and forensics layer** — the incident record a developer or a judge
reads after the fact.

Intended coverage (implementation is a P0 item *late* in the order, not part of this planning pass):

- **Tracing:** one trace for the whole swarm run, with spans for each worker, each policy check,
  the quarantine, the reassignment, the developer patch, the `pytest` run, and the reviewer.
- **Structured logs:** `security.policy_violation`, `security.tool_denied`,
  `security.agent_quarantined`, `swarm.task_reassigned`, `swarm.replacement_started`,
  `developer.patch_applied`, `swarm.tests_passed`, `swarm.recovery_complete`.

**Sentry must be optional.** With no `SENTRY_DSN` configured, the application runs identically and
emits nothing. Never let an observability dependency sit on the demo's critical path.

The strongest version of this story is that a real telemetry observation drives a real project
improvement — recorded honestly in `docs/CODEX_DEVLOG.md`, never invented.

---

## 10. OpenAI's role

OpenAI provides **intelligence, never the security decision**.

Permitted responsibilities:

- the final independent **Reviewer**,
- a developer-facing **incident explanation** ("here is why this request was suspicious"),
- security-incident reasoning and summarization,
- possibly red-team payload generation, later.

**The rule, restated because it is the one that matters:** AgentShield's deny/quarantine decision
is deterministic. An LLM may *explain* an incident only **after** the deterministic decision has
already been made and recorded. No model output is ever an input to a policy outcome.

---

## 11. RunPod's role (optional, P1)

We have a RunPod GPU available. It is **not required for the MVP** and must never be on the
critical path.

The intended story, once the Live Swarm Demo works:

> The original Security Researcher runs on a hosted sponsor model and becomes compromised.
> AgentShield quarantines it. The **Replacement Researcher runs on self-hosted Qwen behind vLLM on
> RunPod** and completes the task.

That demonstrates AgentShield is model-provider-independent: the immune response does not care
which model the tissue was made of.

This is cheap to reach because the existing `app/gateway/vllm_provider.py` already speaks the
OpenAI-compatible `POST /v1/chat/completions` contract against an arbitrary base URL. A RunPod pod
running `vllm serve` is, from this codebase's point of view, just another endpoint.

**The project must work correctly with RunPod absent, unreachable, or unconfigured.**

---

## 12. Existing simulator vs. new live runtime

Both exist. They are peers, they share a substrate, and neither replaces the other.

| | **Deterministic simulator** (existing) | **Live runtime** (new) |
|---|---|---|
| Purpose | Evaluation, benchmarking, replay — the lab | Protecting a real running swarm — the product |
| Agents | Synthetic nodes (+ optional LLM-backed ones) | Real WorkSwarm workers |
| Clock | Fixed-tick, engine-driven | Event-driven, externally driven by the workflow |
| Attack | Probabilistic propagation across a graph | One real indirect prompt injection |
| Defense | Probabilistic detector (`detector_sensitivity`) | Deterministic path policy |
| Scale | 25–2,500 agents | ~5 named workers |
| Entry point | `POST /api/experiments` | `POST /api/runtime/sessions` (new) |
| Demo role | The red-team/eval lab behind the product | The primary demo |

They share: the `Event`/`EventDraft` schema, `EventEmitter` (sole `seq` assigner), `EventBus`,
`SecurityState`, the snapshot/delta frame protocol, the frontend stream reducer, the typed
security-graph node/edge model, and the Sigma topology renderer.

Keeping the simulator matters for the Warp positioning: "a red-team and runtime resilience platform
for developers building multi-agent applications" needs both halves — run the attack in the lab,
enforce in production. The existing benchmark, replay, before/after-defense comparison, and
remediation machinery is that lab, already built and already tested.

**The simulator must not be rewritten, and its tests must not be weakened.**

---

## 13. Scope and non-goals

### In scope for the MVP — exactly one of each

- **One attack:** indirect prompt injection via a poisoned documentation file.
- **One deterministic policy:** requests under `demo_target/secrets/` are denied.
- **One quarantine flow.**
- **One recovery flow:** replacement worker with trusted context only.
- **One vulnerable demo application:** a tiny `demo_target/` with a real auth bug and a real test.
- **One polished UI demo:** `/demo`.

### Explicitly out of scope

- Additional attack families (credential abuse, tool poisoning, collusion, exfiltration variants)
  until the above works end to end.
- Rewriting the simulation engine, the replay system, or persistence.
- Redesigning the existing frontend.
- A generic "integrate any agent framework" platform. One integration: WorkSwarm.
- Modifying WorkSwarm internals.
- Deep remote WorkSwarm session control. Manual invocation is acceptable for the MVP.
- Unrelated sponsor APIs.
- Large new dependencies. The existing preference for the smallest dependency set holds.
- MCP integration, unless a concrete requirement appears.

### Safety constraints carried over from `docs/BRIEF.md` §10

- Synthetic secrets only. `demo_target/secrets/demo_secret.txt` contains a fabricated string that
  is not a credential to anything.
- The demo target is an isolated sandbox directory with no network egress and no real credentials.
- Adversarial content is confined to `demo_target/` and is clearly labelled as such.
- Deterministic evaluation wherever possible.
