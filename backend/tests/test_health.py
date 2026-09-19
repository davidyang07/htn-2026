import asyncio
import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import check_postgres_reachable
from app.main import app

client = TestClient(app)


def test_health_reachable():
    app.dependency_overrides[check_postgres_reachable] = lambda: True
    try:
        response = client.get("/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "postgres": "reachable"}


def test_health_unreachable():
    app.dependency_overrides[check_postgres_reachable] = lambda: False
    try:
        response = client.get("/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "postgres": "unreachable"}


def test_check_postgres_reachable_returns_false_fast():
    # Nothing listens on 127.0.0.1:1 (a reserved, unbindable port), so this
    # connection is refused almost immediately rather than hanging for the
    # full 3s timeout -- this exercises the real error-handling path, not a mock.
    dead_settings = Settings(postgres_host="127.0.0.1", postgres_port=1)

    start = time.monotonic()
    result = asyncio.run(check_postgres_reachable(dead_settings))
    elapsed = time.monotonic() - start

    assert result is False
    assert elapsed < 3.0
