"""SSE streaming endpoint for the Gateway context."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.board.repository import BoardRepository
from src.shared.database import get_session
from src.shared.events import Event, event_bus

router = APIRouter(tags=["sse"])

# How often sse-starlette emits a keepalive comment (`: ping\n\n`) on an
# otherwise idle SSE stream. Without this, idle connections behind a proxy
# or tunnel can be silently reaped — the browser never realizes the stream
# went dead and stops auto-refreshing the dashboard (T-228).
SSE_PING_INTERVAL_SECONDS = 15


async def _event_generator(
    project_id: UUID,
) -> AsyncGenerator[dict[str, str], None]:
    """Yield SSE events for a project from the event bus.

    Emits an initial ``connected`` frame so the client sees activity
    immediately rather than waiting for the first business event. The
    periodic keepalive is configured at the EventSourceResponse level
    via ``ping``.
    """
    queue = event_bus.subscribe(project_id)
    try:
        yield {
            "event": "connected",
            "data": json.dumps({"type": "connected", "project_id": str(project_id)}),
        }
        while True:
            event: Event = await queue.get()
            yield {
                "event": event.type.value,
                "data": json.dumps({"type": event.type.value, **event.data}),
            }
    finally:
        event_bus.unsubscribe(project_id, queue)


@router.get("/projects/{project_id}/stream")
async def stream_events(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventSourceResponse:
    """Stream real-time events for a project via SSE. Public endpoint."""
    repo = BoardRepository(session)
    project = await repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return EventSourceResponse(
        _event_generator(project_id),
        ping=SSE_PING_INTERVAL_SECONDS,
    )
