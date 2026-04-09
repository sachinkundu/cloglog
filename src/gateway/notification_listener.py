"""Background listener that creates notifications when tasks move to review."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from uuid import UUID

from src.board.repository import BoardRepository
from src.shared.database import async_session_factory
from src.shared.events import Event, EventType, event_bus

logger = logging.getLogger(__name__)


async def _handle_review_event(event: Event) -> None:
    """Create a notification and optionally fire notify-send."""
    task_id = UUID(event.data["task_id"])

    async with async_session_factory() as session:
        repo = BoardRepository(session)
        task = await repo.get_task(task_id)
        if task is None:
            logger.warning("Notification listener: task %s not found", task_id)
            return

        notif = await repo.create_notification(
            project_id=event.project_id,
            task_id=task.id,
            task_title=task.title,
            task_number=task.number,
        )

        # Emit NOTIFICATION_CREATED for SSE fan-out
        await event_bus.publish(
            Event(
                type=EventType.NOTIFICATION_CREATED,
                project_id=event.project_id,
                data={
                    "notification_id": str(notif.id),
                    "task_id": str(task.id),
                    "task_title": task.title,
                    "task_number": task.number,
                },
            )
        )

    # Desktop notification (best-effort, suppressed during tests)
    if os.environ.get("DISPLAY") and not os.environ.get("PYTEST_CURRENT_TEST"):
        with contextlib.suppress(FileNotFoundError):
            await asyncio.create_subprocess_exec(
                "notify-send",
                "cloglog",
                f"T-{task.number}: {task.title} is ready for review",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )


async def run_notification_listener() -> None:
    """Subscribe to all events and handle review transitions."""
    queue = event_bus.subscribe_all()
    try:
        while True:
            event = await queue.get()
            if (
                event.type == EventType.TASK_STATUS_CHANGED
                and event.data.get("new_status") == "review"
            ):
                try:
                    await _handle_review_event(event)
                except Exception:
                    logger.exception("Notification listener error")
    finally:
        event_bus.unsubscribe_all(queue)
