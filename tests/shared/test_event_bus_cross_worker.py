"""Cross-worker EventBus tests (T-228).

Each gunicorn worker runs its own EventBus instance backed by an in-process
asyncio queue. To make events published in worker A visible to an SSE
subscriber attached on worker B, every publish issues NOTIFY on a shared
Postgres channel and every worker LISTENs for echoes from peers.

These tests simulate the two-worker setup by instantiating two EventBus
objects on the same test database. We intentionally do NOT spin up two
gunicorn workers — the EventBus instance is the unit that owns the
local-vs-cross boundary, so two instances reproduce the failure mode
``--workers 2`` exposes without any process plumbing.
"""

from __future__ import annotations

import asyncio
import uuid
from uuid import uuid4

import pytest

from src.shared.events import Event, EventBus, EventType


def _dsn(test_db_name: str) -> str:
    return f"postgresql+asyncpg://cloglog:cloglog_dev@localhost:5432/{test_db_name}"


async def _wait_for_listener(bus: EventBus, timeout: float = 5.0) -> None:
    await asyncio.wait_for(bus._listener_ready.wait(), timeout=timeout)


@pytest.mark.asyncio
async def test_event_published_on_worker_a_reaches_subscriber_on_worker_b(
    test_db_name: str,
) -> None:
    """The whole point of T-228: cross-worker fan-out actually works."""
    worker_a = EventBus()
    worker_b = EventBus()
    worker_a.configure_cross_worker(_dsn(test_db_name))
    worker_b.configure_cross_worker(_dsn(test_db_name))

    await worker_a.start_listener()
    await worker_b.start_listener()
    try:
        await _wait_for_listener(worker_a)
        await _wait_for_listener(worker_b)

        project_id = uuid4()
        queue_b = worker_b.subscribe(project_id)
        # Publish on A; B must observe it via Postgres NOTIFY fan-in.
        await worker_a.publish(
            Event(
                type=EventType.TASK_STATUS_CHANGED,
                project_id=project_id,
                data={"task_id": str(uuid.uuid4()), "new_status": "review"},
            )
        )
        event = await asyncio.wait_for(queue_b.get(), timeout=5.0)
        assert event.type is EventType.TASK_STATUS_CHANGED
        assert event.project_id == project_id
        assert event.data["new_status"] == "review"
    finally:
        await worker_a.stop_listener()
        await worker_b.stop_listener()


@pytest.mark.asyncio
async def test_publisher_does_not_double_deliver_its_own_notify_echo(
    test_db_name: str,
) -> None:
    """A worker's local subscribers must see exactly one event per publish.

    Postgres delivers NOTIFY back to every LISTEN connection — including
    the publisher's own. Without source-id deduping the local subscriber
    would see the event twice (once from the local fan-out, once from the
    LISTEN echo). Pin the dedupe so a future refactor can't regress it.
    """
    bus = EventBus()
    bus.configure_cross_worker(_dsn(test_db_name))
    await bus.start_listener()
    try:
        await _wait_for_listener(bus)

        project_id = uuid4()
        queue = bus.subscribe(project_id)
        await bus.publish(Event(type=EventType.TASK_CREATED, project_id=project_id, data={"x": 1}))
        event = await asyncio.wait_for(queue.get(), timeout=5.0)
        assert event.data == {"x": 1}

        # Give the LISTEN echo a window to (incorrectly) re-enqueue.
        await asyncio.sleep(0.5)
        assert queue.empty(), "publisher's own NOTIFY echo was double-delivered locally"
    finally:
        await bus.stop_listener()


@pytest.mark.asyncio
async def test_oversize_payload_is_dropped_locally_logged_no_crash(
    test_db_name: str,
) -> None:
    """Postgres NOTIFY caps at 8000 bytes — keep local fan-out, drop mirror.

    Local subscribers still get the event so the publishing worker's UI
    stays correct; cross-worker subscribers miss it. This is the right
    failure mode (some workers see, none crash) until we move oversize
    payloads to a side channel.
    """
    bus = EventBus()
    bus.configure_cross_worker(_dsn(test_db_name))
    await bus.start_listener()
    try:
        await _wait_for_listener(bus)
        project_id = uuid4()
        queue = bus.subscribe(project_id)
        big = "x" * 9000
        await bus.publish(
            Event(type=EventType.BULK_IMPORT, project_id=project_id, data={"blob": big})
        )
        # Local subscriber still receives (cross-worker mirror is the part skipped).
        event = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert event.data["blob"] == big
    finally:
        await bus.stop_listener()


@pytest.mark.asyncio
async def test_local_only_mode_unaffected_by_cross_worker_code(test_db_name: str) -> None:
    """Without configure_cross_worker(), publish() must stay synchronous local fan-out.

    Most unit tests rely on this — they construct an EventBus, subscribe,
    publish, and expect the event to land instantly with no DB involvement.
    """
    bus = EventBus()
    project_id = uuid4()
    queue = bus.subscribe(project_id)
    await bus.publish(Event(type=EventType.TASK_CREATED, project_id=project_id, data={}))
    event = await asyncio.wait_for(queue.get(), timeout=0.5)
    assert event.type is EventType.TASK_CREATED
