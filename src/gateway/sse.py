"""SSE streaming endpoint for the Gateway context."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from src.gateway.auth import CurrentProject
from src.shared.events import Event, event_bus

router = APIRouter(prefix="/gateway", tags=["gateway"])


async def _event_generator(
    project_id: UUID,
) -> AsyncGenerator[dict[str, str], None]:
    """Yield SSE events for a project from the event bus."""
    queue = event_bus.subscribe(project_id)
    try:
        while True:
            event: Event = await queue.get()
            yield {
                "event": event.type.value,
                "data": json.dumps({"type": event.type.value, **event.data}),
            }
    finally:
        event_bus.unsubscribe(project_id, queue)


@router.get("/events/{project_id}")
async def stream_events(
    project_id: UUID,
    project: CurrentProject,
) -> EventSourceResponse:
    """Stream real-time events for a project via SSE."""
    if project.id != project_id:
        raise HTTPException(status_code=403, detail="Not authorized for this project")

    return EventSourceResponse(_event_generator(project_id))
