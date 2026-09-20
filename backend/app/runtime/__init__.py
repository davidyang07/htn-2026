"""AgentShield live runtime: the external security control plane for a real
running multi-agent workflow (docs/ARCHITECTURE.md).

Deliberately NOT part of app/engine/ -- this package does network and
filesystem I/O and holds mutable per-session state, both of which
app/engine/'s purity contract forbids (docs/SPEC.md §1 decision 2).
app/agents/runtime.py already sits outside the engine for the same reason.

Deliberately NOT part of app/orchestrator/ either: ExperimentRunner owns a
wall-clock tick loop over a generated WorldState, while a live session has no
ticks and advances only when the external workflow calls in
(docs/ARCHITECTURE.md §6).

What it reuses unchanged: app/events/emitter.py (sole seq assigner),
app/events/bus.py (fan-out + ring buffer), app/schemas/events.py,
app/schemas/frames.py, and app/engine/state.py::SecurityState.

Modules:
    policy.py     -- pure, total, deterministic allow/deny decision
    resources.py  -- the fetch half, reachable only after an allow
    session.py    -- LiveRuntimeSession: workers, artifacts, quarantine, tainting
    registry.py   -- in-memory dict[UUID, LiveRuntimeSession]
    explain.py    -- optional, post-hoc, developer-facing incident explanation
"""
