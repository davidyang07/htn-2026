import asyncio
import uuid

from app.persistence.registry import WriterRegistry


class _FakeWriter:
    def __init__(self) -> None:
        self.cancelled = False

    async def cancel(self) -> None:
        self.cancelled = True


def test_add_then_get_returns_same_writer():
    registry = WriterRegistry()
    experiment_id = uuid.uuid4()
    writer = _FakeWriter()
    registry.add(experiment_id, writer)
    assert registry.get(experiment_id) is writer


def test_get_missing_id_returns_none():
    registry = WriterRegistry()
    assert registry.get(uuid.uuid4()) is None


def test_remove_then_get_returns_none():
    registry = WriterRegistry()
    experiment_id = uuid.uuid4()
    registry.add(experiment_id, _FakeWriter())
    registry.remove(experiment_id)
    assert registry.get(experiment_id) is None


def test_shutdown_all_cancels_every_writer_and_clears_registry():
    async def run() -> None:
        registry = WriterRegistry()
        id_a, id_b = uuid.uuid4(), uuid.uuid4()
        writer_a, writer_b = _FakeWriter(), _FakeWriter()
        registry.add(id_a, writer_a)
        registry.add(id_b, writer_b)

        await registry.shutdown_all()

        assert writer_a.cancelled
        assert writer_b.cancelled
        assert registry.get(id_a) is None
        assert registry.get(id_b) is None

    asyncio.run(run())
