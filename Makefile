.PHONY: dev test lint types verify-determinism migrate benchmark benchmark-audit golden-demo import-demo agentshield-test

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
