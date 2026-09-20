# RunPod replacement provider

## Deployment record

Status as of 2026-09-20: **not deployed**.

This Codex environment did not expose RunPod MCP, so no RunPod catalog was
queried through the account and no billable resource was created. The two
pre-existing stopped ComfyUI pods were not started, stopped, changed, deleted,
or reused. A live deployment, endpoint verification, cost observation, and
latency measurements remain external work.

| Field | Planned value | Observed value |
| --- | --- | --- |
| Resource | New vLLM-oriented Pod | Not created |
| GPU | NVIDIA RTX 4090, 24 GB | Not allocated |
| Hourly cost | Community from $0.34/hr; Secure listed at $0.74/hr | Not incurred |
| Model | `Qwen/Qwen2.5-Coder-7B-Instruct` | Not downloaded |
| vLLM image | `vllm/vllm-openai:v0.29.0` | Not pulled |
| API port | `8000/http` | Not exposed |
| Cold startup | Measure from pod start to first healthy `/health` | Not measured |
| First completion | Measure first successful chat after health | Not measured |
| Warm completion | Measure immediate second chat | Not measured |

The rate is a planning estimate, not a quote. RunPod publishes per-second Pod
billing and current GPU rates on its [official pricing page](https://www.runpod.io/pricing);
re-check the selected host immediately before approving creation. A 4090 is the
preferred target because the 7.61B-parameter model fits in 24 GB and the GPU is
fast without paying for datacenter-scale memory. The model's current config is
32,768 tokens, enough for the Replacement Researcher's trusted context, and its
[model card](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct) recommends
vLLM for serving.

## Planned container

Create a **new** Pod. Do not select, clone, or mutate either stopped ComfyUI
Pod. No SSH port or local SSH setup is needed.

- Container image: `vllm/vllm-openai:v0.29.0`
- Exposed port: `8000/http`
- Environment: `VLLM_API_KEY=<new random value entered outside git>`
- Container disk: at least 30 GB
- Volume: optional model cache; do not attach an existing ComfyUI volume
- Docker IPC: host, as recommended by the
  [official vLLM Docker guide](https://docs.vllm.ai/en/stable/deployment/docker/)

Container arguments:

```text
--model Qwen/Qwen2.5-Coder-7B-Instruct
--served-model-name Qwen/Qwen2.5-Coder-7B-Instruct
--host 0.0.0.0
--port 8000
--dtype auto
--max-model-len 32768
--gpu-memory-utilization 0.90
```

`VLLM_API_KEY` is read directly by vLLM; it must not be placed in the argument
list, terminal history, logs, this document, or git. vLLM documents that this
key protects OpenAI-compatible paths but not every server path, so the Pod is
an ephemeral demo resource, not an internet-facing production security
boundary. Stop it immediately after verification. See the
[vLLM security guidance](https://docs.vllm.ai/en/v0.29.0/usage/security/).

## Endpoint and local configuration

For a new Pod id `<new-pod-id>`, RunPod's documented HTTP proxy format is:

```text
https://<new-pod-id>-8000.proxy.runpod.net
```

The application accepts either that service root or the `/v1` base and derives
all three required routes:

```text
GET  https://<new-pod-id>-8000.proxy.runpod.net/health
GET  https://<new-pod-id>-8000.proxy.runpod.net/v1/models
POST https://<new-pod-id>-8000.proxy.runpod.net/v1/chat/completions
```

Set these only in the git-ignored repository `.env` or the process environment:

```dotenv
RUNPOD_MODEL_BASE_URL=https://<new-pod-id>-8000.proxy.runpod.net/v1
RUNPOD_MODEL_API_KEY=<same new random value>
RUNPOD_MODEL_NAME=Qwen/Qwen2.5-Coder-7B-Instruct
```

The endpoint is replacement-only. `AGENTSHIELD_MODEL_*` / WorkSwarm's default
continues to back every normal P0 worker.

## Health and latency verification

The verifier performs, in order, `GET /health`, `GET /v1/models`, and two
`POST /v1/chat/completions` calls. It requires the configured model id and a
non-empty OpenAI-compatible completion. Output contains only the endpoint host,
model id, status codes, response sizes, and timings—never the key, prompt,
completion, or full endpoint URL.

Immediate verification:

```bash
make runpod-check
```

Cold-start measurement immediately after starting the new Pod:

```bash
RUNPOD_CHECK_WAIT_SECONDS=900 make runpod-check
```

The JSON fields to copy back into the deployment record are
`cold_start_ms`, `first_completion.latency_ms`, and
`warm_completion.latency_ms`. Exit status is `0` only when all required checks
pass, `1` for an unhealthy endpoint, and `2` when RunPod is not configured.

## Selection and fallback runbook

RunPod is considered healthy only when all four observations pass: health,
configured model advertised, first completion, and warm completion. Selection
then applies this matrix:

| RunPod state | Replacement Researcher | Event metadata |
| --- | --- | --- |
| Configured and all checks pass | RunPod/vLLM | `provider_route=runpod`, `fallback_used=false` |
| Missing | Normal sponsor model | `provider_route=sponsor_fallback`, `fallback_used=true` |
| Connection refused/unreachable | Normal sponsor model | `provider_route=sponsor_fallback`, `fallback_used=true` |
| Probe timeout | Normal sponsor model | `provider_route=sponsor_fallback`, `fallback_used=true` |
| Wrong model or malformed response | Normal sponsor model | `provider_route=sponsor_fallback`, `fallback_used=true` |
| Fails after preflight | Retry once on the normal sponsor model | Actual answering provider is recorded |
| RunPod and sponsor both absent | Existing deterministic stand-in | No model-call event is emitted |

The original Security Researcher, Repo Analyst, Developer, and Reviewer never
move to RunPod. A provider returns text only. It cannot decide allow/deny,
quarantine a worker, change trust state, read a resource, or seed replacement
context. Those operations remain in AgentShield's deterministic policy and
runtime session.

When diagnosing a fallback:

1. Run `make runpod-check` and retain the credential-free JSON.
2. If `health.ok` is false, inspect the new Pod's container log in the RunPod
   console. Do not use or modify either ComfyUI Pod.
3. If `models.expected_model_found` is false, make
   `RUNPOD_MODEL_NAME` exactly match `/v1/models` and `--served-model-name`.
4. If chat fails, verify port `8000/http`, the `VLLM_API_KEY` environment
   value, and that the selected image finished loading weights.
5. Leave fallback enabled. Do not bypass verification or route a provider into
   AgentShield's policy APIs to make a demo turn green.

## Restart before judging

A stopped Pod is intentionally treated as unavailable. Before deciding the
integration is broken:

1. In RunPod, locate the **new Pod id recorded for this stream**, not either
   pre-existing ComfyUI Pod.
2. Start that Pod in the console. Starting it is billable and requires the
   account's normal explicit approval.
3. Immediately run:

   ```bash
   RUNPOD_CHECK_WAIT_SECONDS=900 make runpod-check
   ```

4. Wait for `ready: true`; record cold, first, and warm timings in the table at
   the top of this document.
5. Run the demo and confirm the Replacement Researcher's model events say
   `provider_route=runpod`. If they say `sponsor_fallback`, report fallback—not
   RunPod success.

No local SSH is part of this procedure.

## Shutdown

After smoke testing, stop the newly created Pod from its RunPod console page.
Record its exact id and final state in the deployment table. If using
`runpodctl`, resolve and visually verify that exact new id first, then run only:

```bash
runpodctl pod stop <new-pod-id>
```

Never run a bulk stop/delete command and never substitute either existing
ComfyUI Pod id. Stopping preserves the Pod for a later demo; delete only when
the owner explicitly chooses to remove this stream's new resource. Re-run
`make runpod-check` after stopping: an unhealthy result plus sponsor fallback
is the expected, functional P0 state.
