# `demo_target/secrets/` — protected, synthetic, never read

`demo_secret.txt` holds a **fabricated** string. It is a credential to
nothing, it authenticates against no service, and it exists only so the Live
Swarm Demo has a concrete resource to protect.

`backend/app/runtime/policy.py` denies every request whose path resolves under
this directory, deterministically and **before any read happens**. No code
path on the demo route opens this file — not to check it, not to hash it, not
to length-check it. The demo's central claim (`docs/DEMO.md` §5) is that the
contents never reach a worker's context, a model request, an event payload, a
log line, a Sentry trace, or the UI.

`.claude/settings.json` additionally denies this directory to Claude Code, so
an assistant working in this repository cannot read it either.

> **Caveat, verified the hard way:** Claude Code loads `.claude/settings.json`
> at session start. A deny rule added *during* a session does not take effect
> until the next one, so the rule above protects every future session but did
> not protect the session that wrote it.
