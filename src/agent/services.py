"""Business logic for the Agent bounded context."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.agent.repository import AgentRepository
from src.board.repository import BoardRepository
from src.shared.config import settings
from src.shared.events import Event, EventType, event_bus


class AgentService:
    def __init__(self, repo: AgentRepository, board_repo: BoardRepository) -> None:
        self._repo = repo
        self._board_repo = board_repo

    # --- Registration ---

    async def register(
        self, project_id: UUID, worktree_path: str, branch_name: str
    ) -> dict[str, object]:
        """Register or reconnect a worktree. Returns registration info."""
        worktree, is_new = await self._repo.upsert_worktree(project_id, worktree_path, branch_name)

        # End any stale active sessions for this worktree
        old_session = await self._repo.get_active_session(worktree.id)
        if old_session is not None:
            await self._repo.end_session(old_session.id, status="ended")

        session = await self._repo.create_session(worktree.id)

        # Build current task info if worktree has one
        current_task = None
        if worktree.current_task_id is not None:
            task = await self._board_repo.get_task(worktree.current_task_id)
            if task is not None:
                current_task = {
                    "id": task.id,
                    "title": task.title,
                    "description": task.description,
                    "status": task.status,
                    "priority": task.priority,
                }

        await event_bus.publish(
            Event(
                type=EventType.WORKTREE_ONLINE,
                project_id=project_id,
                data={"worktree_id": str(worktree.id), "worktree_path": worktree_path},
            )
        )

        return {
            "worktree_id": worktree.id,
            "session_id": session.id,
            "current_task": current_task,
            "resumed": not is_new,
        }

    # --- Heartbeat ---

    async def heartbeat(self, worktree_id: UUID) -> dict[str, object]:
        """Update heartbeat for the active session of a worktree."""
        session = await self._repo.get_active_session(worktree_id)
        if session is None:
            raise ValueError(f"No active session for worktree {worktree_id}")

        updated = await self._repo.update_heartbeat(session.id)
        assert updated is not None
        return {"status": "ok", "last_heartbeat": updated.last_heartbeat}

    # --- Task Lifecycle ---

    async def start_task(self, worktree_id: UUID, task_id: UUID) -> dict[str, object]:
        """Start working on a task."""
        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        task = await self._board_repo.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        # Assign task to worktree and set status
        await self._board_repo.update_task(task_id, worktree_id=worktree_id, status="in_progress")
        await self._repo.set_worktree_current_task(worktree_id, task_id)

        await event_bus.publish(
            Event(
                type=EventType.TASK_STATUS_CHANGED,
                project_id=worktree.project_id,
                data={
                    "task_id": str(task_id),
                    "worktree_id": str(worktree_id),
                    "status": "in_progress",
                },
            )
        )

        return {"task_id": task_id, "status": "in_progress"}

    async def complete_task(self, worktree_id: UUID, task_id: UUID) -> dict[str, object]:
        """Complete a task and return the next assigned task if any."""
        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        # Mark task done
        await self._board_repo.update_task(task_id, status="done")
        await self._repo.set_worktree_current_task(worktree_id, None)

        await event_bus.publish(
            Event(
                type=EventType.TASK_STATUS_CHANGED,
                project_id=worktree.project_id,
                data={
                    "task_id": str(task_id),
                    "worktree_id": str(worktree_id),
                    "status": "done",
                },
            )
        )

        # Find next assigned task for this worktree
        tasks = await self._board_repo.get_tasks_for_worktree(worktree_id)
        next_task = None
        for t in tasks:
            if t.status == "backlog":
                next_task = {
                    "id": t.id,
                    "title": t.title,
                    "description": t.description,
                    "status": t.status,
                    "priority": t.priority,
                }
                break

        return {"completed_task_id": task_id, "next_task": next_task}

    async def update_task_status(self, worktree_id: UUID, task_id: UUID, status: str) -> None:
        """Update a task's status (e.g. to review, blocked)."""
        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        await self._board_repo.update_task(task_id, status=status)

        await event_bus.publish(
            Event(
                type=EventType.TASK_STATUS_CHANGED,
                project_id=worktree.project_id,
                data={
                    "task_id": str(task_id),
                    "worktree_id": str(worktree_id),
                    "status": status,
                },
            )
        )

    # --- Unregister ---

    async def unregister(self, worktree_id: UUID) -> None:
        """End the active session and mark worktree offline."""
        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        session = await self._repo.get_active_session(worktree_id)
        if session is not None:
            await self._repo.end_session(session.id)

        await self._repo.set_worktree_offline(worktree_id)

        await event_bus.publish(
            Event(
                type=EventType.WORKTREE_OFFLINE,
                project_id=worktree.project_id,
                data={"worktree_id": str(worktree_id)},
            )
        )

    # --- Heartbeat Timeout ---

    async def check_heartbeat_timeouts(self) -> list[UUID]:
        """Find and mark timed-out sessions. Returns list of affected worktree IDs."""
        cutoff = datetime.now(UTC) - timedelta(seconds=settings.heartbeat_timeout_seconds)
        timed_out = await self._repo.get_timed_out_sessions(cutoff)

        worktree_ids = []
        for session in timed_out:
            await self._repo.end_session(session.id, status="timed_out")
            await self._repo.set_worktree_offline(session.worktree_id)
            worktree_ids.append(session.worktree_id)

            worktree = await self._repo.get_worktree(session.worktree_id)
            if worktree is not None:
                await event_bus.publish(
                    Event(
                        type=EventType.WORKTREE_OFFLINE,
                        project_id=worktree.project_id,
                        data={
                            "worktree_id": str(session.worktree_id),
                            "reason": "heartbeat_timeout",
                        },
                    )
                )

        return worktree_ids

    # --- Query (implements WorktreeService protocol) ---

    async def get_worktrees_for_project(self, project_id: UUID) -> list[dict[str, object]]:
        worktrees = await self._repo.get_worktrees_for_project(project_id)
        result = []
        for w in worktrees:
            last_hb = await self._repo.get_latest_heartbeat(w.id)
            result.append(
                {
                    "id": w.id,
                    "project_id": w.project_id,
                    "name": w.branch_name or w.worktree_path.rsplit("/", 1)[-1],
                    "worktree_path": w.worktree_path,
                    "branch_name": w.branch_name,
                    "status": w.status,
                    "current_task_id": w.current_task_id,
                    "last_heartbeat": last_hb,
                    "created_at": w.created_at,
                }
            )
        return result

    async def get_worktree(self, worktree_id: UUID) -> dict[str, object] | None:
        w = await self._repo.get_worktree(worktree_id)
        if w is None:
            return None
        return {
            "id": w.id,
            "project_id": w.project_id,
            "worktree_path": w.worktree_path,
            "branch_name": w.branch_name,
            "status": w.status,
            "current_task_id": w.current_task_id,
            "created_at": w.created_at,
        }
