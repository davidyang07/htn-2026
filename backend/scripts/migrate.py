#!/usr/bin/env python3
"""Standalone entry point for `make migrate` -- applies pending migrations
against whatever Postgres the current environment/Settings point at, without
booting the full app. Useful for CI to verify migrations apply cleanly."""

import asyncio

from app.config import get_settings
from app.db import create_pool
from app.persistence.migrate import run_migrations


async def main() -> None:
    pool = await create_pool(get_settings())
    try:
        await run_migrations(pool)
    finally:
        await pool.close()
    print("migrations applied")


if __name__ == "__main__":
    asyncio.run(main())
