# Sentry sponsor-demo stream

Sentry is the demo's optional forensics layer. It records what happened after
the policy decision; it never makes the decision. The shipped P0 integration
has already delivered transaction and log envelopes successfully. This stream
keeps that implementation and hardens its correlation, scrubbing, and failure
isolation.

## Observed trace shape

The application-created spans below are the hierarchy emitted by the current
code. Sentry's FastAPI and HTTP integrations may insert client/server request
spans between the WorkSwarm span and the AgentShield span; those wrappers are
useful network evidence and do not change the causal order.

```text
agentshield.demo
├─ workswarm.analysis
│  ├─ workswarm.repo_analyst.fetch
│  │  └─ agentshield.policy_check (for each requested path)
│  ├─ workswarm.repo_analyst
│  ├─ workswarm.security_researcher.fetch
│  │  └─ agentshield.policy_check
│  ├─ workswarm.security_researcher
│  └─ resource-request HTTP continuation
│     ├─ agentshield.policy_check
│     └─ agentshield.quarantine (deny branch)
├─ swarm.task_reassigned
│  └─ swarm.task_reassigned (AgentShield continuation)
├─ workswarm.replacement_researcher.fetch
│  └─ agentshield.policy_check
├─ workswarm.replacement_researcher
├─ developer.regression_test
├─ developer.regression_red
├─ developer.patch
├─ pytest.after_fix
├─ reviewer.verify
└─ swarm.recovery_complete
```

`sentry-trace` and `baggage` are forwarded on every WorkSwarm-to-AgentShield
HTTP request, so both processes join the same distributed trace. The
`workswarm.analysis` span is intentionally broad because Repo Analyst and
Security Researcher execute concurrently; forcing one beneath the other would
misrepresent the workflow.

## Structured logs

Filter on `event.name` to follow the searchable incident narrative:

```text
security.policy_violation
security.tool_denied
security.agent_quarantined
swarm.task_reassigned
swarm.replacement_started
developer.regression_failed
developer.patch_applied
swarm.tests_passed
swarm.recovery_complete
```

`developer.regression_failed` is the expected RED proof against the vulnerable
module. It is distinct from `developer.patch_applied`; the post-fix GREEN proof
is `swarm.tests_passed` with `phase=after_fix` and `pytest_exit_code=0`.

## Data-safety contract

Allowed correlation fields include:

- `run_id` / `session_id`, `worker_id`, `role`, and task or artifact identifiers
- `event_type`, requested `resource_path`, policy `rule` / `policy_result`
- `security_state`, replacement worker relationships, and phase
- model/provider identity and latency, never model input or output
- pytest exit code, pass state, and safe artifact/path lists

The helpers drop unapproved attributes. Approved nested collections are
recursively filtered before serialization. A final SDK egress scrubber filters
authorization and cookie headers, API keys, passwords, secrets and tokens,
prompts, messages, completions, request/response bodies, resource content,
repository/file contents, and source code. Resource **paths** remain visible;
protected resource **contents** do not.

With `SENTRY_DSN` absent, initialization returns disabled and every helper is a
no-op. SDK initialization, span start/finish, metadata, log emission, and trace
header failures are isolated from the application. A bad or unreachable Sentry
transport cannot change policy, quarantine, reassignment, responses, or the
workflow result.

## What to click during judging

1. Open the AgentShield Sentry project and choose **Explore**, then the traces
   or spans view. Select the demo environment and a short recent time range.
2. Filter for `transaction:agentshield.demo`, sort newest first, and open the
   latest trace.
3. Confirm the `run_id` matches the terminal's session ID. Expand the deny
   branch from `agentshield.policy_check` through quarantine, reassignment,
   replacement, RED, patch, GREEN, review, and recovery.
4. Switch Explore to the **Logs** dataset. Filter by the same `run_id`, then
   narrow with `event.name:security.tool_denied` or another name above.
5. Open the log attributes to show the requested path, policy rule/result,
   worker and security state. Point out that no protected contents, prompt, or
   completion is present.

Sentry documents Explore as the query surface for both `spans` and `logs` data
sets: <https://docs.sentry.io/api/explore/query-explore-events-in-table-format/>.

## Find a real issue during final testing

Do not pre-write a claim that Sentry found a bug. During a full rehearsal:

1. Note the terminal session ID and open that exact `run_id` in Sentry.
2. Check for a real anomaly: an error event, missing expected stage, unexpected
   duplicate stage, broken parent/child continuation, or an outlier model/span
   latency.
3. Compare the trace with the runtime event feed and terminal output. A visual
   oddity is not yet a bug; reproduce it on a second run.
4. If reproducible, capture the trace ID, affected span/log, timestamps, and
   the mismatch. Write the smallest regression test before changing code.
5. Only after the fix is verified should `docs/CODEX_DEVLOG.md` say that Sentry
   found the issue. If no anomaly is found, report exactly that.

No new issue is claimed by this document. It is a procedure for using Sentry
to discover and substantiate one during final testing.
