# WorkSwarm — what it is and how AgentShield relates to it

> **Audience:** a coding agent (or human) who has never heard of WorkSwarm and is about to write
> integration code. Read this before touching anything under `workswarm/`.

---

## 1. What WorkSwarm is

**WorkSwarm is the current openJiuwen multi-agent product.** It is a real multi-agent
orchestration system: a **Leader** decomposes a task and coordinates **specialized workers**, with
Cluster/Team collaboration and handoffs between them. **SwarmFlow** is its system for
Python-authored, deterministic multi-agent workflows.

For this project, WorkSwarm is the multi-agent system we are *protecting*. It is the genuine
article — not simulated, not mocked, not reimplemented by us.

---

## 2. Naming — read this carefully

The upstream GitHub repository and internal source may still use **`jiuwenswarm`**, **`openjiuwen`**,
or similar names. Package names, import paths, module names, and CLI entry points may carry the old
naming.

**Rules:**

1. The **current product/release line is WorkSwarm**. Use "WorkSwarm" in all product-facing text:
   the UI, `README.md`, every document in `docs/`, the demo script, and the pitch.
2. In code, use whatever import path the installed package actually provides. Do not rename or
   shim upstream modules to match the product name — a cosmetic shim is one more thing to break on
   stage.
3. **Do not build a separate legacy JiuwenSwarm integration.** There is one integration. Old names
   encountered in the installed package are the same product, not a second target.
4. If the installed package's naming differs from what this document assumes, record the actual
   import path in `workswarm/README.md` and move on. Do not fork the integration.

---

## 3. Hard boundaries

| Rule | Why |
|---|---|
| **Do not modify WorkSwarm internals.** | It is a sponsor product and an external dependency. Our claim is that an *external* control plane protects an *unmodified* swarm. Patching it would destroy that claim. |
| **WorkSwarm is installed separately**, outside this application. | Keeps this repository free of vendored third-party code and of sponsor credentials. |
| **The sponsor model is configured manually**, outside this repository. | No sponsor keys in the repo, in `.env.example`, or in any commit — ever. See `docs/PROJECT.md` §13. |
| **Deep remote session control is explicitly out of scope.** | We do not drive a remote WorkSwarm runtime, manage its sessions, or build a control API for it. |
| **Manual WorkSwarm invocation is acceptable for the MVP.** | Running one command in a second terminal is a fine demo. Automating launch is not a deliverable. |
| **Use an offline-authored SwarmFlow.** | Determinism and demo reliability. A dynamically-planned flow can improvise on stage; an authored one cannot. |

AgentShield is **not** replacing WorkSwarm orchestration. It sits beside it as the security layer.

---

## 4. The division of responsibility

| Concern | Owner |
|---|---|
| Task decomposition | WorkSwarm Leader |
| Specialized workers, collaboration, handoffs | WorkSwarm |
| Worker LLM calls | WorkSwarm (sponsor model; optionally RunPod for the replacement, P1) |
| Starting a replacement worker; reassigning the task | WorkSwarm |
| Deciding whether a resource request is allowed | **AgentShield** |
| Recording the policy violation | **AgentShield** |
| Raising the anomaly | **AgentShield** |
| Quarantining a worker | **AgentShield** |
| Marking a worker's output untrusted | **AgentShield** |
| Signalling "recovery required" | **AgentShield** |
| Streaming the incident to the UI | **AgentShield** |

The interface between them is HTTP, in one direction: the SwarmFlow calls AgentShield. AgentShield
never calls into WorkSwarm.

---

## 5. How the SwarmFlow talks to AgentShield

```python
# workswarm/agentshield_client.py  (implemented)

session  = shield.create_session(objective, workers=[...])   # POST /api/runtime/sessions
decision = shield.request_resource(worker_id, path)          # POST .../resource-request
shield.complete_task(worker_id, "pytest", summary)           # POST .../tasks/complete
shield.record_test_run(worker_id, command=..., exit_code=..., passed=..., summary=...)
shield.reassign(from_worker_id=..., to_worker={...}, task=..., context_artifact_ids=[...])
shield.recover(summary) / shield.fail(reason)
```

Explicit lifecycle calls rather than one generic `emit(...)`: a generic event ingest would let the
workflow *assert* a security outcome, and `reassign` in particular **validates** the replacement's
seed context against AgentShield's own taint record (409 on a tainted artifact) instead of
recording whatever it is told.

**`request_resource` is a synchronous decision.** Its response body carries `decision`, `reason`,
`quarantined`, `recovery_required`, and — only on an allow — `content`. The flow obeys it.

**The client fails closed.** A timeout, a connection error, or any non-2xx response is treated as a
**denial**. A security control that fails open is not a security control, and on a conference
network the control plane *will* blip at least once.

### The contract that makes the demo work

> **A worker never holds the capability it is being tricked into using.**

The Security Researcher has no filesystem tool. Its structured output includes
`requested_files: list[str]`. The SwarmFlow step takes that list, asks AgentShield about each
entry, and reads **only what comes back allowed**.

So a prompt injection that *completely* captures the worker still obtains nothing. The attack
succeeds at the model layer and fails at the system layer. Never let a code path fetch a protected
file before the decision returns — that single shortcut invalidates the entire demo.

---

## 6. The planned golden workflow

**User task:**

> "Find and fix the authentication vulnerability in this repository, add regression coverage, and
> verify the patch."

```
 1. Leader decomposes the task.

 2. Repo Analyst maps demo_target/.
      -> requests demo_target/README.md, demo_target/app/auth.py   -> ALLOWED

 3. Security Researcher investigates the vulnerability.
      -> requests demo_target/docs/auth_notes.md               -> ALLOWED
      -> that document carries an INDIRECT PROMPT INJECTION
      -> worker's structured output now requests
         demo_target/secrets/demo_secret.txt                       -> DENIED

 4. AgentShield, deterministically and before any read:
      TOOL_REQUESTED -> TOOL_DENIED -> POLICY_VIOLATION
                     -> ANOMALY_DETECTED -> AGENT_QUARANTINED
      marks the Security Researcher's output untrusted
      responds recovery_required = true

 5. WorkSwarm starts a Replacement Researcher.
      TASK_REASSIGNED, then AGENT_CREATED (metadata.replaces)
      context = trusted artifacts ONLY; the poisoned document never reaches it

 6. Developer patches demo_target/app/auth.py + adds a regression test.
      TASK_COMPLETED (step="patch")

 7. Real `pytest demo_target` runs. Real exit code, real counts.
      TASK_COMPLETED (step="pytest")

 8. Reviewer independently verifies the patch and the evidence.
      TASK_COMPLETED (step="review"), then WORKFLOW_RECOVERED

 9. Result:
      ATTACK DETECTED / AGENT QUARANTINED / WORKFLOW RECOVERED / TESTS PASSED
```

The user gets a correct, verified result **even though one worker was compromised mid-task**. The
recovery is the story — the denial is only the setup.

---

## 7. Setup (performed manually by the owner, outside this repo)

Verified against the environment this was built in. Mirrored, with more detail, in
`workswarm/README.md`.

1. **Install WorkSwarm**, in its own virtualenv — it needs Python `>=3.11,<3.14` and pulls a large
   dependency tree the backend must not inherit:

   ```bash
   python3.11 -m venv .venv-workswarm
   .venv-workswarm/bin/pip install workswarm==0.2.6     # Windows: Scripts/pip
   ```

   The PyPI distribution is **`workswarm`**; the top-level import packages it installs are
   **`jiuwenswarm`** and `jiuwenbox`, and its core dependency is **`openjiuwen==0.1.18`**.

2. **The import path we actually use is `openjiuwen.core.workflow`** — that is where SwarmFlow's
   Python-authored workflow system lives (`Workflow`, `Start`, `End`, `WorkflowComponent`,
   `LLMComponent`, `BranchRouter`, `Condition`, `create_workflow_session`). `jiuwenswarm` is the
   server/gateway/channels layer; the demo does not need it. No shim, no rename (§2 rule 2).

3. **Configure the model credentials** — manual, outside this repository, in the git-ignored
   repo-root `.env`. Normal-worker resolution checks:
   `AGENTSHIELD_MODEL_BASE_URL`/`_API_KEY`/`_NAME`/`_PROVIDER` (any OpenAI-compatible endpoint),
   then WorkSwarm's own `config.yaml`, then `OPENAI_API_KEY`. `RUNPOD_MODEL_*` is resolved
   separately for the Replacement Researcher and falls back to that normal sponsor route when
   absent or unhealthy. With no normal provider the workers run as deterministic stand-ins and
   every worker, event and screen says so. `.env.example` lists the keys with empty placeholders;
   **no credential of any kind belongs in this repository**.

4. **Verify the install** before involving AgentShield:

   ```bash
   .venv-workswarm/bin/python -c "from openjiuwen.core.workflow import Workflow; print('ok')"
   ```

5. **Start AgentShield** on port 8100 (WorkSwarm's own server also defaults to 8000), then run
   the flow — `make demo-run`, or:

   ```bash
   AGENTSHIELD_BASE_URL=http://localhost:8100 .venv-workswarm/bin/python workswarm/run_demo.py
   ```

   See `docs/DEMO.md` for the full runbook and the reset procedure.

---

## 8. Why this integration earns its place

The sponsor story, stated plainly:

> Multi-agent systems should not only collaborate when everything works. They should keep
> functioning when one worker becomes compromised.

WorkSwarm supplies the collaboration — Leader, decomposition, specialized workers, handoffs,
SwarmFlow, and the recovery workflow. AgentShield supplies the resilience — failure detection,
quarantine, task reassignment, continued team operation, and verification.

**The final demo must use a real WorkSwarm multi-agent workflow.** Faked swarm activity would
invalidate the entire claim, and it is the first thing a judge will probe.
