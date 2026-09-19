from fastapi import APIRouter, HTTPException

from app.schemas.frames import StreamFrame

router = APIRouter(prefix="/api/schema", tags=["schema"])


@router.get("/events", response_model=StreamFrame)
async def get_stream_frame_schema() -> StreamFrame:
    """Never called by any client. Its only purpose is to make StreamFrame's
    discriminated union appear in /openapi.json, which is what pulls the
    WebSocket payload shapes into the generated TypeScript types
    (SPEC §1 decision 4)."""
    raise HTTPException(status_code=501, detail="schema-only endpoint")
