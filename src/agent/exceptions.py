"""Typed exceptions for the Agent bounded context."""

from __future__ import annotations

from src.agent.interfaces import BlockerDTO
from src.board.models import Task


class TaskBlockedError(Exception):
    """Raised when start_task (or update_task_status into in_progress) is
    rejected because one or more blockers are not yet resolved.

    Carries the structured blocker list so the route layer can emit the
    ``code=task_blocked`` 409 payload described in the F-11 spec.
    """

    code = "task_blocked"

    def __init__(self, task: Task, blockers: list[BlockerDTO]) -> None:
        self.task = task
        self.blockers = blockers
        super().__init__(
            f"Cannot start task T-{task.number}: {len(blockers)} blocker(s) not resolved."
        )
