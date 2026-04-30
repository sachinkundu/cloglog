from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)


# Channel name for cross-worker event mirroring. Single channel is fine
# at our scale — listeners filter by project_id locally.
NOTIFY_CHANNEL = "cloglog_events"

# Postgres NOTIFY payload limit is 8000 bytes. Stay well under to leave
# headroom for the JSON envelope.
_NOTIFY_PAYLOAD_LIMIT = 7800


class EventType(StrEnum):
    TASK_STATUS_CHANGED = "task_status_changed"
    WORKTREE_ONLINE = "worktree_online"
    WORKTREE_OFFLINE = "worktree_offline"
    DOCUMENT_ATTACHED = "document_attached"
    EPIC_CREATED = "epic_created"
    EPIC_DELETED = "epic_deleted"
    FEATURE_CREATED = "feature_created"
    FEATURE_DELETED = "feature_deleted"
    TASK_CREATED = "task_created"
    TASK_DELETED = "task_deleted"
    TASK_NOTE_ADDED = "task_note_added"
    BULK_IMPORT = "bulk_import"
    NOTIFICATION_CREATED = "notification_created"
    DEPENDENCY_ADDED = "dependency_added"
    DEPENDENCY_REMOVED = "dependency_removed"
    EPIC_REORDERED = "epic_reordered"
    FEATURE_REORDERED = "feature_reordered"
    TASK_REORDERED = "task_reordered"
    TASK_RETIRED = "task_retired"
    BULK_RETIRED = "bulk_retired"
    BULK_AGENTS_REMOVED = "bulk_agents_removed"
    # Emitted when the review engine claims the first turn of a codex review
    # on a (pr_url, head_sha). Carries ``pr_url`` so the dashboard can flip
    # the "codex reviewed" badge on the matching task card (T-260). The
    # badge is boolean — subsequent turns emit the same event but it is
    # idempotent on the frontend (a re-fetch of the board reads the same
    # projected value).
    REVIEW_CODEX_TURN_STARTED = "review_codex_turn_started"
    # T-358: typed event classes the desktop-toast dispatcher subscribes to.
    # Routine state changes (PR opened, → review, pr_merged, agent_started)
    # still fire NOTIFICATION_CREATED for the dashboard bell but do NOT toast.
    # Only operator-attention events below trigger ``notify-send``.
    AGENT_BLOCKED = "agent_blocked"
    AGENT_UNREGISTERED = "agent_unregistered"
    AUTO_MERGE_STALLED = "auto_merge_stalled"
    CHANGES_REQUESTED_REPEAT = "changes_requested_repeat"
    CLOSE_WAVE_FAILED = "close_wave_failed"


@dataclass
class Event:
    type: EventType
    project_id: UUID
    data: dict[str, Any] = field(default_factory=dict)


def _to_asyncpg_dsn(url: str) -> str:
    """Strip the SQLAlchemy ``+asyncpg`` driver suffix asyncpg.connect rejects."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


class EventBus:
    """Pub/sub for SSE fan-out with cross-worker mirroring.

    The bus runs in two modes:

    * **Local-only** (default, used by tests): ``publish()`` enqueues to
      in-process subscribers immediately. No DB involvement.
    * **Cross-worker** (production): ``configure_cross_worker(dsn)`` followed
      by ``start_listener()`` opens a Postgres LISTEN connection. Every
      ``publish()`` also issues ``NOTIFY cloglog_events, <payload>``; every
      worker's listener decodes incoming notifications and fans them out to
      local subscribers. A per-process ``_source_id`` is embedded in the
      payload so a worker that publishes does not double-deliver when it
      receives the echo of its own NOTIFY.
    """

    def __init__(self) -> None:
        self._subscribers: dict[UUID, list[asyncio.Queue[Event]]] = {}
        self._global_subscribers: list[asyncio.Queue[Event]] = []
        # Stable per-process id used to filter our own NOTIFY echoes.
        self._source_id: str = uuid.uuid4().hex
        self._dsn: str | None = None
        self._publisher_conn: asyncpg.Connection | None = None
        self._publisher_lock = asyncio.Lock()
        self._listener_task: asyncio.Task[None] | None = None
        # Set when the listener has at least once successfully attached to
        # the channel. Tests use this to avoid racing the first publish.
        self._listener_ready = asyncio.Event()

    def subscribe(self, project_id: UUID) -> asyncio.Queue[Event]:
        """Subscribe to events for a single project."""
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.setdefault(project_id, []).append(queue)
        return queue

    def subscribe_all(self) -> asyncio.Queue[Event]:
        """Subscribe to events from all projects."""
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._global_subscribers.append(queue)
        return queue

    def unsubscribe(self, project_id: UUID, queue: asyncio.Queue[Event]) -> None:
        if project_id in self._subscribers:
            self._subscribers[project_id] = [
                q for q in self._subscribers[project_id] if q is not queue
            ]

    def unsubscribe_all(self, queue: asyncio.Queue[Event]) -> None:
        self._global_subscribers = [q for q in self._global_subscribers if q is not queue]

    async def publish(self, event: Event) -> None:
        # The publishing worker fans out to BOTH project subscribers (SSE
        # streams) and global subscribers (notification_listener, etc.)
        # because it owns the event end-to-end on this turn.
        self._fan_out(event, include_global=True)
        if self._dsn is not None:
            await self._notify(event)

    def _fan_out(self, event: Event, *, include_global: bool) -> None:
        for queue in self._subscribers.get(event.project_id, []):
            queue.put_nowait(event)
        if include_global:
            for queue in self._global_subscribers:
                queue.put_nowait(event)

    def _encode(self, event: Event) -> str:
        return json.dumps(
            {
                "src": self._source_id,
                "type": event.type.value,
                "project_id": str(event.project_id),
                "data": event.data,
            },
            default=str,
        )

    def _decode(self, payload: str) -> tuple[str, Event] | None:
        try:
            msg = json.loads(payload)
            return msg["src"], Event(
                type=EventType(msg["type"]),
                project_id=UUID(msg["project_id"]),
                data=msg.get("data", {}),
            )
        except (ValueError, KeyError, TypeError):
            logger.exception("event_bus: malformed NOTIFY payload (dropped)")
            return None

    async def _notify(self, event: Event) -> None:
        payload = self._encode(event)
        if len(payload.encode("utf-8")) > _NOTIFY_PAYLOAD_LIMIT:
            # NOTIFY rejects payloads >8000 bytes. Drop the cross-worker
            # mirror and surface the size; local subscribers still got it.
            logger.warning(
                "event_bus: payload over NOTIFY limit (type=%s project_id=%s size=%d) — "
                "skipping cross-worker mirror",
                event.type.value,
                event.project_id,
                len(payload),
            )
            return
        try:
            async with self._publisher_lock:
                conn = await self._get_publisher_conn()
                # Bound parameter avoids hand-quoting NUL/quote in payload.
                await conn.execute("SELECT pg_notify($1, $2)", NOTIFY_CHANNEL, payload)
        except Exception:
            # Cross-worker mirror is best-effort. Local subscribers already
            # received the event; surface the failure and reset the
            # connection so the next publish reconnects.
            logger.exception("event_bus: NOTIFY failed; resetting publisher connection")
            with contextlib.suppress(Exception):
                if self._publisher_conn is not None:
                    await self._publisher_conn.close()
            self._publisher_conn = None

    async def _get_publisher_conn(self) -> asyncpg.Connection:
        assert self._dsn is not None
        if self._publisher_conn is None or self._publisher_conn.is_closed():
            self._publisher_conn = await asyncpg.connect(_to_asyncpg_dsn(self._dsn))
        return self._publisher_conn

    def configure_cross_worker(self, dsn: str) -> None:
        """Enable Postgres-backed cross-worker mirror. Call before start_listener()."""
        self._dsn = dsn

    async def start_listener(self) -> None:
        """Spawn the LISTEN background task. No-op when not configured or already running."""
        if self._dsn is None or self._listener_task is not None:
            return
        self._listener_ready.clear()
        self._listener_task = asyncio.create_task(self._listener_loop())

    async def stop_listener(self) -> None:
        """Cancel the LISTEN task and close pooled connections."""
        if self._listener_task is not None:
            self._listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None
        async with self._publisher_lock:
            if self._publisher_conn is not None and not self._publisher_conn.is_closed():
                with contextlib.suppress(Exception):
                    await self._publisher_conn.close()
            self._publisher_conn = None
        self._listener_ready.clear()

    async def _listener_loop(self) -> None:
        assert self._dsn is not None
        backoff = 1.0
        while True:
            conn: asyncpg.Connection | None = None
            try:
                conn = await asyncpg.connect(_to_asyncpg_dsn(self._dsn))
                await conn.add_listener(NOTIFY_CHANNEL, self._on_notification)
                logger.info(
                    "event_bus: LISTEN attached on channel %s (worker=%s)",
                    NOTIFY_CHANNEL,
                    self._source_id,
                )
                self._listener_ready.set()
                backoff = 1.0
                # Block while the connection stays healthy. asyncpg dispatches
                # NOTIFY callbacks on its own — we just need to keep the loop
                # alive and detect connection loss.
                while not conn.is_closed():
                    await asyncio.sleep(15)
            except asyncio.CancelledError:
                if conn is not None and not conn.is_closed():
                    with contextlib.suppress(Exception):
                        await conn.close()
                raise
            except Exception:
                logger.exception(
                    "event_bus: LISTEN connection lost; reconnecting in %.1fs", backoff
                )
                if conn is not None and not conn.is_closed():
                    with contextlib.suppress(Exception):
                        await conn.close()
                self._listener_ready.clear()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    def _on_notification(
        self,
        connection: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        decoded = self._decode(payload)
        if decoded is None:
            return
        source, event = decoded
        if source == self._source_id:
            # We already fanned this out locally inside publish().
            return
        # Cross-worker mirror: only fan out to project SSE subscribers, NOT to
        # `_global_subscribers`. The notification_listener subscribes via
        # subscribe_all() and runs on every worker — fanning the mirrored
        # event into it would have every peer worker insert a duplicate
        # notification row for a single TASK_STATUS_CHANGED → review
        # transition (codex review on PR #233).
        self._fan_out(event, include_global=False)


event_bus = EventBus()
