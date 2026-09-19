`docs/PLAN.md` is the authoritative architecture, domain-model, migration, and roadmap document for the current product direction (the Multi-Agent Adversarial Resilience Platform pivot). `docs/SPEC.md` remains authoritative for the low-level mechanism it defines (event schema, derived-keyed RNG, fixed-tick engine, snapshot/delta protocol) — that mechanism is preserved, not replaced. `docs/BRIEF.md` provides original project motivation and broader context. Where SPEC/BRIEF's product framing conflicts with PLAN, follow PLAN; where SPEC and BRIEF conflict on mechanism, follow SPEC.

- Implement only the phase/scope explicitly requested by the user. Do not speculatively implement functionality assigned to future phases.
- Prefer the simplest architecture and smallest dependency set that satisfies the current requirements. Do not add dependencies without a concrete requirement.
- Do not weaken, delete, skip, or rewrite tests merely to make an implementation pass.
- Run the relevant tests, linting, type checking, and other available verification before claiming work is complete. Never claim something works based only on inspection when it can reasonably be executed or tested.
- Never commit secrets, credentials, API keys, `.env` files, generated credentials, or local machine configuration.
- Treat Linux/WSL as the canonical local development environment.
- Preserve documented architectural boundaries.
- If implementation requires deviating materially from SPEC, stop and surface the deviation and rationale before making it.
- Prefer small, reviewable changes over unrelated cleanup or refactoring. Do not change unrelated files while completing a scoped task.
