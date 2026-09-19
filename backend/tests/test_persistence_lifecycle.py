"""DB-independent coverage of persistence's failure-tolerance contract at the
route layer: a Postgres outage (no pool, or a writer that fails to start)
must never block experiment creation, and a failed writer init must never
leave an orphaned bus subscription or a half-registered writer behind.
Exercises app.state.pg_pool directly rather than depending on a real
Postgres being reachable, so this runs in every environment.
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.orchestrator.registry import registry as experiment_registry
from app.persistence.registry import writer_registry


def _start_experiment(client: TestClient) -> dict:
    resp = client.post(
        "/api/experiments", json={"seed": 1, "node_count": 25, "max_ticks": 1}
    )
    assert resp.status_code == 201
    return resp.json()


def test_create_experiment_with_no_pool_runs_live_only_no_writer_registered():
    with TestClient(app) as client:
        client.app.state.pg_pool = None
        summary = _start_experiment(client)
        exp_id = uuid.UUID(summary["experiment_id"])
        assert writer_registry.get(exp_id) is None


def test_create_experiment_with_broken_pool_leaves_no_orphan_writer_or_subscription():
    class _BrokenPool:
        async def execute(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("simulated insert failure")

        async def close(self) -> None:
            pass

    with TestClient(app) as client:
        client.app.state.pg_pool = _BrokenPool()
        summary = _start_experiment(client)
        exp_id = uuid.UUID(summary["experiment_id"])

        # Experiment creation itself must succeed regardless of the writer
        # init failure -- persistence is decoupled from the live run.
        assert writer_registry.get(exp_id) is None

        runner = experiment_registry.get(exp_id)
        assert runner is not None
        # No orphaned queue left registered on the bus from the failed
        # writer.start() -- it must have unsubscribed on the way out.
        assert len(runner.bus._subscribers) == 0
