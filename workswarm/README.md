# `workswarm/` — the WorkSwarm integration

Read `docs/WORKSWARM.md` first. It defines the product relationship, the naming
rules (upstream says `jiuwenswarm` / `openjiuwen`; the product is **WorkSwarm**),
and the hard boundaries.

This directory holds **our** side of the integration only. WorkSwarm itself is
installed separately and is never modified or vendored here.

## What is actually installed

Verified against the environment this was built in:

| | |
|---|---|
| PyPI distribution | `workswarm==0.2.6` |
| Top-level import packages it installs | **`jiuwenswarm`**, `jiuwenbox` |
| Its core dependency | `openjiuwen==0.1.18` |
| Python | `>=3.11,<3.14` (this venv: 3.11.9) |

**The import path we actually use is `openjiuwen.core.workflow`** — that is
where SwarmFlow's Python-authored workflow system lives (`Workflow`, `Start`,
`End`, `WorkflowComponent`, `LLMComponent`, `BranchRouter`, `Condition`,
`create_workflow_session`). `jiuwenswarm` is the server/gateway/channels layer
and the demo does not need it.

No shim, no rename: the code imports what the package actually provides
(`docs/WORKSWARM.md` §2 rule 2).

## Layout

```
workswarm/
├── agentshield_client.py   # HTTP client for /api/runtime/*. FAILS CLOSED.
├── config.py               # model + control-plane resolution; no secrets here
├── injection.py            # the naive instruction-follower (no WorkSwarm import)
├── workers.py              # LLMComponent workers, and the stand-ins
├── prompts.py              # per-worker system prompts
├── patcher.py              # sandbox-bounded writes + the deterministic fix
├── verify.py               # the real `pytest demo_target` subprocess runner
├── telemetry.py            # optional Sentry transaction/spans/logs
├── flows/auth_fix_flow.py  # the offline-authored SwarmFlow
├── run_demo.py             # the single command that runs the demo
├── reset_demo.py           # restores the vulnerable baseline between runs
└── tests/                  # bridge tests; run with the BACKEND venv
```

## Local setup

WorkSwarm goes in **its own virtualenv**, separate from `backend/.venv`: it
needs Python <3.14 and pulls in a large dependency tree that the backend must
not inherit.

```bash
python3.11 -m venv .venv-workswarm
.venv-workswarm/bin/pip install workswarm==0.2.6      # Windows: Scripts/pip
```

That is the whole install. Verified working with:

```bash
.venv-workswarm/bin/python -c "from openjiuwen.core.workflow import Workflow; print('ok')"
```

### Model credentials (manual, never committed)

The normal P0 workers use the first configured sponsor route: explicit
`AGENTSHIELD_MODEL_*`, WorkSwarm's own `config.yaml`, then `OPENAI_API_KEY`.
RunPod is resolved separately for the Replacement Researcher only:

| Variable group | Use |
|---|---|
| `AGENTSHIELD_MODEL_BASE_URL` / `_API_KEY` / `_NAME` / `_PROVIDER` | The front door. OpenAI, a RunPod vLLM pod, Ollama (`http://localhost:11434/v1`), LM Studio, a sponsor gateway. |
| `RUNPOD_MODEL_BASE_URL` / `_API_KEY` / `_NAME` | Optional Replacement Researcher route; missing or unhealthy endpoints fall back to the sponsor route. |
| `OPENAI_API_KEY` (+ optional `OPENAI_BASE_URL`, `OPENAI_MODEL`) | Plain OpenAI. |
| *(none set)* | The workers run as **deterministic stand-ins**. |

`.env.example` lists every key. **No credential of any kind belongs in this
repository** — `.env` is git-ignored and `.env.example` holds empty
placeholders only.

### What the stand-ins are, and are not

With no model endpoint configured the reasoning workers fall back to
`workswarm/workers.py`'s deterministic components. They are still real
WorkSwarm workflow components — scheduled, retried and traced by the same
engine — and the Security Researcher's stand-in is genuinely
injection-susceptible: `workswarm/injection.py` reads the document AgentShield
released to it and extracts the paths that document *instructs its reader to
fetch*. Nothing hardcodes `demo_target/secrets/demo_secret.txt`; retarget the
poisoned paragraph and it asks for the new path, delete it and it asks for
nothing. `workswarm/tests/test_bridge.py` pins all three behaviours.

This is surfaced, never hidden: every worker is registered with
`model_backed` set truthfully, the `/demo` screen labels each worker
`model-backed` or `deterministic stand-in`, and `run_demo.py` prints which
mode the run used.

The Replacement Researcher can independently use a verified RunPod/vLLM
endpoint. It falls back to the normal sponsor model when RunPod is missing,
unhealthy, unreachable, or timed out, and records the provider that actually
answered. Deployment, cost, verification, restart, and shutdown instructions
are in [`docs/streams/runpod.md`](../docs/streams/runpod.md).

## Running it

See `docs/DEMO.md` for the full runbook. The short version, from the
repository root with the backend already up on 8100:

```bash
AGENTSHIELD_BASE_URL=http://localhost:8100 .venv-workswarm/bin/python workswarm/run_demo.py
AGENTSHIELD_BASE_URL=http://localhost:8100 .venv-workswarm/bin/python workswarm/reset_demo.py
```

or `make demo-run` / `make demo-reset`.

## Tests

The bridge tests deliberately avoid importing the WorkSwarm engine, so the
security-relevant half of this integration is verifiable with the backend's
own venv and in CI, without installing WorkSwarm:

```bash
backend/.venv/bin/python -m pytest workswarm      # or: make test-bridge
```

They cover: the client failing **closed** on every transport and HTTP failure
mode; a real denial staying distinguishable from a network failure; writes
outside `demo_target/` and into `demo_target/secrets/` being refused; pytest's
summary line being quoted verbatim; and the instruction-follower following the
document rather than a script.

The flow and the LLM workers are exercised by actually running the demo.

## Boundaries

- **WorkSwarm internals are never modified.** Our claim is that an *external*
  control plane protects an *unmodified* swarm; patching it would destroy that
  claim.
- **The bridge calls in one direction only.** The SwarmFlow calls AgentShield;
  AgentShield never calls into WorkSwarm.
- **`request_resource` fails closed.** A timeout, a connection error, or any
  non-2xx is a denial.
- **A worker never holds the capability it is being tricked into using.** No
  component in `flows/` opens a file for a worker. A worker names what it
  wants; only what comes back allowed is ever read.
