"""Protocols and DTOs exposed by the Agent context."""

from __future__ import annotations

from typing import Literal, Protocol, TypedDict
from uuid import UUID

from src.board.interfaces import BoardBlockerDTO


class WorktreeService(Protocol):
    """Used by Gateway to query worktree state."""

    async def get_worktrees_for_project(self, project_id: UUID) -> list[dict[str, object]]: ...

    async def get_worktree(self, worktree_id: UUID) -> dict[str, object] | None: ...


class PipelineBlocker(TypedDict):
    """An Agent-domain blocker: the task's pipeline predecessor is not done.

    Owned by Agent (not Board) because the spec→plan→impl workflow is a
    task-type concern, not a dependency-table concern.
    """

    kind: Literal["pipeline"]
    predecessor_task_type: str
    task_id: str
    task_number: int
    task_title: str
    status: str
    reason: Literal["artifact_missing", "not_done"]


BlockerDTO = BoardBlockerDTO | PipelineBlocker
