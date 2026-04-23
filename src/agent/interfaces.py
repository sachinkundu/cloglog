"""Protocols and DTOs exposed by the Agent context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict
from uuid import UUID

from src.board.interfaces import BoardBlockerDTO


class WorktreeService(Protocol):
    """Used by Gateway to query worktree state."""

    async def get_worktrees_for_project(self, project_id: UUID) -> list[dict[str, object]]: ...

    async def get_worktree(self, worktree_id: UUID) -> dict[str, object] | None: ...


@dataclass(frozen=True)
class WorktreeRow:
    """Read-only snapshot of a worktree, carried across the Agent boundary.

    Gateway consumers (T-278 per-PR review-root resolution) receive this DTO
    instead of the ORM row so they never bind to ``src.agent.models``.
    """

    id: UUID
    project_id: UUID
    worktree_path: str
    branch_name: str
    status: str


class IWorktreeQuery(Protocol):
    """Read-only query port exposed by the Agent context.

    Used by Gateway's review engine to resolve the PR's owning worktree
    without importing ``src.agent.models`` or ``src.agent.repository`` —
    the same Open Host Service pattern as ``IReviewTurnRegistry`` in the
    Review context (see ``docs/ddd-context-map.md``). T-278.
    """

    async def find_by_branch(self, project_id: UUID, branch_name: str) -> WorktreeRow | None:
        """Return the worktree (any status) with this branch in this project.

        Returns ``None`` when ``branch_name`` is empty, no match exists, or
        more than one row matches (the empty-branch data trap — see the
        docstring on ``AgentRepository.get_worktree_by_branch``). The
        caller must treat ``None`` as "fall back to the host-level root."
        """
        ...


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
