"""Protocols exposed by the Agent context to other contexts."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class WorktreeService(Protocol):
    """Used by Gateway to query worktree state."""

    async def get_worktrees_for_project(self, project_id: UUID) -> list[dict[str, object]]: ...

    async def get_worktree(self, worktree_id: UUID) -> dict[str, object] | None: ...
