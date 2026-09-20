# Adversarial QA and security hardening

Date: 2026-09-20  
Branch: `feat/qa`  
Baseline: `p0-baseline` (`2d19a52f2de92175d7a8d2861665723218ffd2ff`)

## Outcome

The P0 deny, quarantine, recovery, and trusted-context flow remains unchanged.
This pass added adversarial coverage around its enforcement boundaries and
fixed three concrete bypasses discovered by that coverage.

## Issues discovered and fixed

1. **Windows path aliases:** Win32 trims trailing dots and spaces from path
   components, so `secrets.` could alias the protected `secrets` directory.
   Sandbox-relative colons also admitted NTFS alternate-data-stream syntax.
   Policy now recognizes protected aliases and rejects ambiguous/stream paths.
2. **Incomplete quarantine at the API boundary:** quarantined workers were
   blocked from task and resource operations but could still submit model-call
   evidence and artifacts. Every worker-authored endpoint now requires an
   active worker; control-plane reassignment remains available for recovery.
3. **Resolved-resource escape:** the reader checked that a resolved path stayed
   inside the repository, which allowed a symlink beneath `demo_target/app` to
   resolve into `backend/app` or `demo_target/secrets`. Resolved targets must
   now remain inside `demo_target` and pass policy again after resolution.

## Invariants proven

- Traversal, nested traversal, Windows separators, mixed/doubled separators,
  absolute Unix paths, drive paths, UNC paths, schemes, case variants, empty
  inputs, non-string inputs, NULs, and overlong paths fail closed.
- Exact protected segments are denied while near-misses such as
  `demo_target/secrets_backup/x` and
  `demo_target/app/secrets-policy.md` remain ordinary sandbox paths.
- A deny is returned and its event cascade is recorded before the resource
  reader can run. The reader independently reauthorizes both the requested and
  resolved paths, so direct calls and symlink resolution cannot bypass policy.
- Quarantined workers cannot start/complete tasks, record model calls, create
  artifacts, report tests, or regain resource access through the runtime API.
- A mixed trusted/tainted reassignment is rejected atomically. Replacement
  Researcher creation records trusted artifacts only and never includes a
  tainted artifact.
- Running from the demo target imports `demo_target/app`, not `backend/app`.
- Optional Sentry, OpenAI, RunPod, and vLLM configuration may be absent while
  the runtime still denies, quarantines, reassigns, and recovers.
- `reset_demo.py` restores the committed vulnerable module, reruns its baseline
  suite, and can be run repeatedly without broad deletion.

## Safe leak verification

`backend/scripts/verify_no_secret_leaks.py` derives its comparison needle from
the local synthetic fixture at runtime. It never prints the value and skips the
fixture itself. By default it scans `backend/.artifacts`; runtime logs, reports,
or additional artifact directories can be passed as positional paths. A match
returns exit code 1, invalid explicit inputs return 2, and a clean scan returns
0. Unit tests use a separate synthetic test needle, including a match split
across streaming chunk boundaries.

## Verification results

- Two consecutive real resets: both exit 0, confirm the vulnerable baseline,
  and report `pytest demo_target: 6 passed, 1 warning`.
- Focused policy/runtime/security set: 215 tests collected; 100% passed.
- WorkSwarm bridge/reset/import tests: 50 passed.
- Full backend suite from `backend/`: 590 collected; 569 passed and 21 skipped
  (Postgres-dependent tests skip when the optional test database is absent).
- Branch-scoped Ruff check over every changed Python file: `All checks passed!`.
- Determinism verifier: `PASS: 330 events identical`.
- Existing AgentShield security gate: `2/2 findings passed`.
- Leak verifier after artifact generation: passed, 2 files scanned.

## Existing repository findings

A repo-wide Ruff run still reports 26 `I001` import-order findings in untouched
baseline tests. They are outside this focused workstream; all files changed by
this branch are clean. FastAPI/Starlette also emit two dependency deprecation
warnings in TestClient-based suites. Neither affects runtime behavior, but both
should be handled by a separate maintenance workstream.
