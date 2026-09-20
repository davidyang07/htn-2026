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
