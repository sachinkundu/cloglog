"""Protocols exposed by the Board context to other contexts."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class TaskAssignmentService(Protocol):
    """Used by Agent context to claim/release tasks."""

    async def assign_task_to_worktree(
        self, task_id: UUID, worktree_id: UUID
    ) -> None: ...

    async def unassign_task_from_worktree(
        self, task_id: UUID
    ) -> None: ...

    async def get_tasks_for_worktree(
        self, worktree_id: UUID
    ) -> list[dict[str, object]]: ...


class TaskStatusService(Protocol):
    """Used by Agent context to move tasks between columns."""

    async def start_task(self, task_id: UUID, worktree_id: UUID) -> None: ...

    async def complete_task(self, task_id: UUID) -> dict[str, object] | None:
        """Complete a task and return the next assigned task, or None."""
        ...

    async def update_task_status(self, task_id: UUID, status: str) -> None: ...
