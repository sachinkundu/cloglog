"""Webhook consumers — route GitHub PR events to owning worktree agents.

AgentNotifierConsumer resolves PR events to the owning agent's inbox file
and appends structured JSON messages. For PR_MERGED events, it also updates
Task.pr_merged in the database.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType

logger = logging.getLogger(__name__)


class AgentNotifierConsumer:
    """Route PR events to the owning worktree agent via inbox file."""

    _handled = {
        WebhookEventType.PR_MERGED,
        WebhookEventType.PR_CLOSED,
        WebhookEventType.REVIEW_SUBMITTED,
        WebhookEventType.CHECK_RUN_COMPLETED,
    }

    def __init__(self, session_factory: Any = None) -> None:
        self._session_factory = session_factory

    def handles(self, event: WebhookEvent) -> bool:
        return event.type in self._handled

    async def handle(self, event: WebhookEvent) -> None:
        from src.shared.database import async_session_factory

        factory = self._session_factory or async_session_factory
        async with factory() as session:
            # Resolve which agent owns this PR
            worktree_id = await self._resolve_agent(event, session)

            # For PR_MERGED, update the task's pr_merged flag regardless of agent status
            if event.type == WebhookEventType.PR_MERGED:
                await self._mark_pr_merged(event.pr_url, session)

            if worktree_id is None:
                logger.debug("No agent found for PR %s", event.pr_url)
                return

            # Build message based on event type
            message = self._build_message(event)
            if message is None:
                return

            # Append to agent inbox (not write_text — multiple events can arrive quickly)
            inbox_path = Path(f"/tmp/cloglog-inbox-{worktree_id}")
            with inbox_path.open("a") as f:
                f.write(json.dumps(message) + "\n")
            logger.info(
                "Notified agent %s of %s on PR #%d",
                worktree_id,
                event.type,
                event.pr_number,
            )

    async def _resolve_agent(self, event: WebhookEvent, session: AsyncSession) -> UUID | None:
        """Resolve PR event to owning worktree ID.

        Primary: match Task.pr_url.
        Fallback: match Worktree.branch_name (for PRs opened before agent sets pr_url).
        """
        from src.board.repository import BoardRepository

        repo = BoardRepository(session)

        # Primary: match by pr_url
        task = await repo.find_task_by_pr_url(event.pr_url)
        if task is not None and task.worktree_id is not None:
            return task.worktree_id

        # Fallback: match by branch name
        from src.agent.repository import AgentRepository

        agent_repo = AgentRepository(session)
        project = await repo.find_project_by_repo(event.repo_full_name)
        if project is None:
            return None
        worktree = await agent_repo.get_worktree_by_branch(project.id, event.head_branch)
        if worktree is not None:
            return worktree.id

        return None

    async def _mark_pr_merged(self, pr_url: str, session: AsyncSession) -> None:
        """Update Task.pr_merged = True for the task matching this PR URL."""
        from src.board.repository import BoardRepository

        repo = BoardRepository(session)
        task = await repo.find_task_by_pr_url(pr_url)
        if task is not None:
            await repo.update_task(task.id, pr_merged=True)
            logger.info("Marked task %s pr_merged=True for %s", task.id, pr_url)

    def _build_message(self, event: WebhookEvent) -> dict[str, Any] | None:
        if event.type == WebhookEventType.PR_MERGED:
            return {
                "type": "pr_merged",
                "pr_url": event.pr_url,
                "pr_number": event.pr_number,
                "message": (
                    f"PR #{event.pr_number} has been MERGED. "
                    "If this is a spec/plan task, call report_artifact. "
                    "Then call get_my_tasks and start the next task."
                ),
            }
        if event.type == WebhookEventType.PR_CLOSED:
            return {
                "type": "pr_closed",
                "pr_url": event.pr_url,
                "pr_number": event.pr_number,
                "message": f"PR #{event.pr_number} was closed without merging.",
            }
        if event.type == WebhookEventType.REVIEW_SUBMITTED:
            review = event.raw.get("review", {})
            state = review.get("state", "")
            body = (review.get("body") or "")[:500]
            return {
                "type": "review_submitted",
                "pr_url": event.pr_url,
                "pr_number": event.pr_number,
                "review_state": state,
                "reviewer": event.sender,
                "body": body,
                "message": (
                    f"Review on PR #{event.pr_number}: {state} by {event.sender}. "
                    + (f"Feedback: {body}" if body else "No comment body.")
                    + (
                        " Address the feedback, push a fix, and move back to review."
                        if state == "changes_requested"
                        else ""
                    )
                ),
            }
        if event.type == WebhookEventType.CHECK_RUN_COMPLETED:
            check = event.raw.get("check_run", {})
            conclusion = check.get("conclusion", "")
            name = check.get("name", "")
            if conclusion == "success":
                return None  # Don't notify on success — only failures matter
            return {
                "type": "ci_failed",
                "pr_url": event.pr_url,
                "pr_number": event.pr_number,
                "check_name": name,
                "conclusion": conclusion,
                "message": (
                    f"CI check '{name}' {conclusion} on PR #{event.pr_number}. "
                    "Use the github-bot skill to read the failed logs and push a fix."
                ),
            }
        return None
