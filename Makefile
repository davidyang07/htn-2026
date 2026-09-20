.PHONY: dev test test-bridge test-demo-target lint types verify-determinism migrate benchmark benchmark-audit golden-demo import-demo agentshield-test demo-backend demo-frontend demo-run demo-reset

dev:
	docker compose up --build

# Backend tests hit a real Postgres (persistence integration tests) -- run
# against a dedicated agentnet_test database, created if absent, so the
# suite never touches dev data. Requires `docker compose up postgres` (or an
# equivalent local Postgres) already running and reachable via the
# POSTGRES_* env vars (defaults: localhost:5432, user/password agentnet).
test:
	PGPASSWORD=$${POSTGRES_PASSWORD:-agentnet_dev} psql -h $${POSTGRES_HOST:-localhost} -p $${POSTGRES_PORT:-5432} -U $${POSTGRES_USER:-agentnet} -tc "SELECT 1 FROM pg_database WHERE datname = 'agentnet_test'" | grep -q 1 || \
	PGPASSWORD=$${POSTGRES_PASSWORD:-agentnet_dev} createdb -h $${POSTGRES_HOST:-localhost} -p $${POSTGRES_PORT:-5432} -U $${POSTGRES_USER:-agentnet} agentnet_test
	cd backend && POSTGRES_DB=agentnet_test .venv/bin/pytest

lint:
	cd backend && .venv/bin/ruff check .
	# The bridge is part of what a p0-baseline tag promises, so it is linted
	# too, with the backend's rule set. demo_target/ is deliberately excluded:
	# it is a separate mini-project with its own import root (`app`), which
	# this config would misread as third-party -- and its files are rewritten
	# by the Developer worker every run.
	backend/.venv/bin/ruff check --config backend/pyproject.toml workswarm/
	cd frontend && npm run lint
	# Next 16 generates PageProps/LayoutProps/RouteContext helpers on demand
	# (next dev/build/typegen) rather than shipping them as static types --
	# `tsc --noEmit` alone errors on any route using them without this.
	cd frontend && npx next typegen
	cd frontend && npx tsc --noEmit

# Requires a backend already running at localhost:8000 (e.g. `make dev`, or
# `cd backend && .venv/bin/uvicorn app.main:app`).
types:
	cd frontend && npx openapi-typescript http://localhost:8000/openapi.json -o src/lib/api/schema.d.ts

# --- Live Swarm Demo (docs/DEMO.md) ---------------------------------------
#
# AgentShield runs on 8100 because WorkSwarm also defaults to 8000. The code
# defaults stay 8000, so the existing simulator setup and CI are untouched --
# these targets are the documented non-conflicting local setup.
AGENTSHIELD_PORT ?= 8100

# Terminal 2.
demo-backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port $(AGENTSHIELD_PORT)

# Terminal 3.
demo-frontend:
	cd frontend && NEXT_PUBLIC_BACKEND_URL=http://localhost:$(AGENTSHIELD_PORT) NEXT_PUBLIC_BACKEND_WS_URL=ws://localhost:$(AGENTSHIELD_PORT) npm run dev

# Terminal 4 -- the demo trigger. Uses the separate WorkSwarm venv.
demo-run:
	AGENTSHIELD_BASE_URL=http://localhost:$(AGENTSHIELD_PORT) .venv-workswarm/bin/python workswarm/run_demo.py

# Between runs: restores the vulnerable baseline and clears live sessions.
demo-reset:
	AGENTSHIELD_BASE_URL=http://localhost:$(AGENTSHIELD_PORT) .venv-workswarm/bin/python workswarm/reset_demo.py

# The WorkSwarm-side bridge tests. Deliberately runnable with the backend's
# own venv -- they never import the WorkSwarm engine, so the security-relevant
# half of the integration is verifiable without installing WorkSwarm.
test-bridge:
	backend/.venv/bin/python -m pytest workswarm

# The vulnerable demo application's own suite.
test-demo-target:
	backend/.venv/bin/python -m pytest demo_target

verify-determinism:
	cd backend && .venv/bin/python scripts/verify_determinism.py

# Applies pending migrations standalone, without booting the full app.
migrate:
	cd backend && .venv/bin/python scripts/migrate.py

# Canonical benchmark suite (Priority 1 of the product-validation brief):
# 12+ attack scenarios, 6+ defense configurations, a 2,500+ agent scale run,
# and a before/after remediation comparison. Zero real provider calls.
# Writes backend/.artifacts/benchmark/{results.json,report.md}.
benchmark:
	cd backend && .venv/bin/python scripts/run_benchmark.py

# Priority 2 of this session's brief: sweeps every attack-scenario/defense-
# variant preset for a remediation opportunity and ranks the results by
# measured retained_utility improvement. Writes
# backend/.artifacts/benchmark/{audit.json,audit.md}.
benchmark-audit:
	cd backend && .venv/bin/python scripts/run_benchmark_audit.py

# The golden demo scenario (Priority 2): one config whose event log narrates
# indirect prompt injection -> propagation -> initial quarantine -> adaptive
# attacker strategy switch -> sentinel compromise -> false threat-memory
# report -> remediation -> re-test -> measurable improvement. Writes
# backend/.artifacts/golden_demo/{report.md,result.json}.
golden-demo:
	cd backend && .venv/bin/python scripts/run_golden_demo.py

# Runs an adversarial scenario against the real LangGraph sample app's
# imported topology (Priority 3). Writes
# backend/.artifacts/external_import/result.json.
import-demo:
	cd backend && .venv/bin/python scripts/run_external_import_demo.py

# CI-friendly pass/fail gate over a fast subset of the benchmark suite plus
# the golden demo (Productization). Exit 0 if every finding passes.
agentshield-test:
	cd backend && .venv/bin/python scripts/agentshield_test.py
