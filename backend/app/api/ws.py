from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.orchestrator.registry import registry
from app.schemas.frames import EventFrame

router = APIRouter()


@router.websocket("/api/experiments/{experiment_id}/stream")
async def experiment_stream(
    websocket: WebSocket, experiment_id: UUID, since_seq: int | None = None
) -> None:
    runner = registry.get(experiment_id)
    if runner is None:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    # Subscribe *before* reading any snapshot/backlog so a concurrent publish
    # can never slip through the gap between the two.
    queue = runner.bus.subscribe()
    try:
        backlog = runner.bus.since(since_seq) if since_seq is not None else None

        if backlog is None:
            snapshot = runner.snapshot()
            await websocket.send_text(snapshot.model_dump_json())
            last_sent_seq = snapshot.last_seq
        else:
            last_sent_seq = since_seq
            for event in backlog:
                await websocket.send_text(EventFrame(event=event).model_dump_json())
                last_sent_seq = event.seq

        while True:
            event = await queue.get()
            if event.seq <= last_sent_seq:
                continue
            await websocket.send_text(EventFrame(event=event).model_dump_json())
            last_sent_seq = event.seq
    except WebSocketDisconnect:
        pass
    finally:
        runner.bus.unsubscribe(queue)
