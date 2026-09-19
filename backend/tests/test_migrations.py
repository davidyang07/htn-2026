import asyncio

from app.db import create_pool
from app.persistence.migrate import run_migrations

from .conftest import TEST_SETTINGS, requires_postgres

pytestmark = requires_postgres


def test_run_migrations_twice_is_idempotent_and_creates_expected_tables():
    async def run() -> None:
        pool = await create_pool(TEST_SETTINGS)
        try:
            await run_migrations(pool)
            await run_migrations(pool)  # second run must be a no-op, not an error

            tables = {
                row["tablename"]
                for row in await pool.fetch(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
            }
            assert {"experiments", "experiment_events", "schema_migrations"} <= tables

            rows = await pool.fetch("SELECT version FROM schema_migrations")
            versions = [row["version"] for row in rows]
            assert versions == sorted(set(versions)), "no duplicate migration rows after re-run"
        finally:
            await pool.close()

    asyncio.run(run())
