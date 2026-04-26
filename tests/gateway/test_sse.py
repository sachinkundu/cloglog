"""Tests for Gateway SSE endpoint."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.gateway import sse as sse_module
from src.gateway.sse import SSE_PING_INTERVAL_SECONDS, _event_generator
from src.shared.events import Event, EventType, event_bus


@pytest.mark.asyncio
async def test_sse_returns_404_for_unknown_project(client: AsyncClient) -> None:
    """SSE endpoint returns 404 for a project that doesn't exist."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/v1/projects/{fake_id}/stream")
    assert response.status_code == 404


def test_stream_endpoint_configures_periodic_ping() -> None:
    """Idle SSE streams must emit a periodic keepalive — without it, proxies/tunnels
    silently reap the connection and the dashboard stops auto-refreshing (T-228)."""
    assert SSE_PING_INTERVAL_SECONDS > 0
    # The endpoint must hand the ping interval to EventSourceResponse so
    # sse-starlette emits the comment frame on idle streams. Pin the wiring
    # so a future "drop ping=" regression is caught.
    src = inspect.getsource(sse_module.stream_events)
    assert "ping=SSE_PING_INTERVAL_SECONDS" in src


@pytest.mark.asyncio
async def test_event_generator_emits_initial_connected_frame() -> None:
    """First SSE frame is a ``connected`` ack so the client sees activity immediately."""
    project_id = uuid4()
    gen = _event_generator(project_id)

    initial = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    assert initial["event"] == "connected"
    assert str(project_id) in initial["data"]

    await gen.aclose()


@pytest.mark.asyncio
async def test_event_generator_yields_published_events() -> None:
    """The SSE event generator yields events published to the event bus."""
    project_id = uuid4()
    gen = _event_generator(project_id)

    # Drain the initial connected frame.
    await asyncio.wait_for(gen.__anext__(), timeout=2.0)

    # Start consuming (this blocks on queue.get)
    next_task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0.05)

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

    # First __anext__ subscribes and yields the connected ack.
    await asyncio.wait_for(gen.__anext__(), timeout=2.0)

    # Subscriber is registered
    assert len(event_bus._subscribers.get(project_id, [])) == 1

    # Park on the next event then cancel
    next_task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0.05)
    next_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await next_task
    await gen.aclose()

    # Subscriber should be removed
    assert len(event_bus._subscribers.get(project_id, [])) == 0
