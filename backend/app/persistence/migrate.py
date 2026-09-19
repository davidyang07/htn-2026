"""Hand-rolled forward-only SQL migration runner.

No ORM/Alembic exists in this codebase (`db.py` uses raw `asyncpg`) and the
schema is two tables with no anticipated near-term churn -- see
docs/PHASE_1_5_PLAN.md §4 for the rationale. Migrations are plain `.sql`
files in `backend/migrations/`, applied in filename order inside a
transaction, tracked in a `schema_migrations` table so repeated runs are
no-ops (idempotent by construction: an applied version is simply skipped).
"""

from pathlib import Path

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _version_of(path: Path) -> int:
    # "0001_initial.sql" -> 1
    return int(path.name.split("_", 1)[0])


async def run_migrations(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     INT PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        applied = {
            row["version"] for row in await conn.fetch("SELECT version FROM schema_migrations")
        }

        for path in _migration_files():
            version = _version_of(path)
            if version in applied:
                continue
            sql = path.read_text()
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)", version
                )
