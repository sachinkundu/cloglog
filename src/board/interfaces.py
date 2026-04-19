"""Protocols exposed by the Board context to other contexts."""

from __future__ import annotations

from typing import Literal, Protocol, TypedDict
from uuid import UUID


class TaskAssignmentService(Protocol):
    """Used by Agent context to claim/release tasks."""

    async def assign_task_to_worktree(self, task_id: UUID, worktree_id: UUID) -> None: ...

    async def unassign_task_from_worktree(self, task_id: UUID) -> None: ...

    async def get_tasks_for_worktree(self, worktree_id: UUID) -> list[dict[str, object]]: ...


class TaskStatusService(Protocol):
    """Used by Agent context to move tasks between columns."""

    async def start_task(self, task_id: UUID, worktree_id: UUID) -> None: ...

    async def complete_task(self, task_id: UUID) -> dict[str, object] | None:
        """Complete a task and return the next assigned task, or None."""
        ...

    async def update_task_status(self, task_id: UUID, status: str) -> None: ...


# --- Blocker query (F-11) ---
# Blockers are structured reasons a task cannot enter ``in_progress``. The
# Board owns the "resolved" semantics for feature and task blockers (it
# knows the underlying data model). Agent owns the pipeline rule.


class FeatureBlocker(TypedDict):
    """A feature dependency that is not yet resolved."""

    kind: Literal["feature"]
    feature_id: str
    feature_number: int
    feature_title: str
    incomplete_task_numbers: list[int]


class TaskBlocker(TypedDict):
    """A task-level ``blocked_by`` edge that is not yet resolved."""

    kind: Literal["task"]
    task_id: str
    task_number: int
    task_title: str
    status: str


BoardBlockerDTO = FeatureBlocker | TaskBlocker


class BoardBlockerQueryPort(Protocol):
    """Used by Agent context to ask Board 'what's blocking this task?'.

    Returns feature and task blockers in stable order (feature first, then
    task, each sorted by .number). Agent composes this with its own
    pipeline-blocker list before raising.
    """

    async def get_unresolved_blockers(self, task_id: UUID) -> list[BoardBlockerDTO]: ...
