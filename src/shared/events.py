from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID


class EventType(StrEnum):
    TASK_STATUS_CHANGED = "task_status_changed"
    WORKTREE_ONLINE = "worktree_online"
    WORKTREE_OFFLINE = "worktree_offline"
    DOCUMENT_ATTACHED = "document_attached"


@dataclass
class Event:
    type: EventType
    project_id: UUID
    data: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """Simple in-process pub/sub for SSE fan-out."""

    def __init__(self) -> None:
        self._subscribers: dict[UUID, list[asyncio.Queue[Event]]] = {}

    def subscribe(self, project_id: UUID) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.setdefault(project_id, []).append(queue)
        return queue

    def unsubscribe(self, project_id: UUID, queue: asyncio.Queue[Event]) -> None:
        if project_id in self._subscribers:
            self._subscribers[project_id] = [
                q for q in self._subscribers[project_id] if q is not queue
            ]

    async def publish(self, event: Event) -> None:
        for queue in self._subscribers.get(event.project_id, []):
            await queue.put(event)


event_bus = EventBus()
