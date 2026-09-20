"""The WorkSwarm integration surface (docs/WORKSWARM.md).

WorkSwarm is the current openJiuwen multi-agent product and is the real
multi-agent system AgentShield protects. It is installed separately (the
`workswarm` distribution, which provides the `openjiuwen` import package), is
configured manually outside this repository, and is NOT modified by us.

This package is the thin bridge in one direction only -- the SwarmFlow calls
AgentShield; AgentShield never calls into WorkSwarm.

Modules:
    agentshield_client.py  -- HTTP client for the live-runtime API; FAILS CLOSED
    config.py              -- model + control-plane resolution
    injection.py           -- the naive instruction-follower (no WorkSwarm import)
    workers.py             -- LLMComponent workers and the deterministic stand-ins
    prompts.py             -- per-worker system prompts
    patcher.py             -- sandbox-bounded writes + the deterministic fix
    verify.py              -- the real `pytest demo_target` subprocess runner
    telemetry.py           -- optional Sentry transaction/spans/structured logs
    flows/auth_fix_flow.py -- the offline-authored SwarmFlow for the demo
    run_demo.py            -- the single command that runs the Live Swarm Demo
    reset_demo.py          -- restores the vulnerable baseline between runs

The contract that makes the demo work: a worker never holds the capability it
is being tricked into using. The Security Researcher has no filesystem tool;
it can only name the resources it wants, and every name goes to AgentShield
BEFORE anything is read.
"""
