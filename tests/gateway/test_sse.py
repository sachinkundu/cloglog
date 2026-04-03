"""Tests for Gateway SSE endpoint."""

from __future__ import annotations

import asyncio
import contextlib
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.gateway.sse import _event_generator
from src.shared.events import Event, EventType, event_bus


@pytest.mark.asyncio
async def test_sse_requires_auth(client: AsyncClient) -> None:
    """SSE endpoint requires a valid API key."""
    response = await client.get("/api/v1/gateway/events/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_sse_rejects_wrong_project(client: AsyncClient) -> None:
    """SSE endpoint rejects requests for a project not matching the API key."""
    create_resp = await client.post(
        "/api/v1/projects",
        json={"name": "sse-wrong-project", "description": "test"},
    )
    assert create_resp.status_code == 201
    api_key = create_resp.json()["api_key"]

    fake_project_id = "00000000-0000-0000-0000-000000000001"
    response = await client.get(
        f"/api/v1/gateway/events/{fake_project_id}",
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_event_generator_yields_published_events() -> None:
    """The SSE event generator yields events published to the event bus."""
    project_id = uuid4()
    gen = _event_generator(project_id)

    # Start consuming (this subscribes to the bus and blocks on queue.get)
    next_task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0.05)  # Let the generator subscribe

    # Publish an event
    await event_bus.publish(
        Event(
            type=EventType.TASK_STATUS_CHANGED,
            project_id=project_id,
            data={"task_id": "abc", "status": "in_progress"},
        )
    )

    result = await asyncio.wait_for(next_task, timeout=2.0)
    assert result["event"] == "task_status_changed"
    assert "task_id" in result["data"]
    assert "in_progress" in result["data"]

    await gen.aclose()


@pytest.mark.asyncio
async def test_event_generator_unsubscribes_on_close() -> None:
    """The generator unsubscribes from the event bus when closed."""
    project_id = uuid4()
    gen = _event_generator(project_id)

    # Start consuming to trigger subscription
    next_task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0.05)

    # Check there's a subscriber
    assert len(event_bus._subscribers.get(project_id, [])) == 1

    # Cancel and close the generator
    next_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await next_task
    await gen.aclose()

    # Subscriber should be removed
    assert len(event_bus._subscribers.get(project_id, [])) == 0
