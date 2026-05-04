"""Webhook consumers — route GitHub PR events to owning worktree agents.

AgentNotifierConsumer resolves PR events to the owning agent's inbox file
and appends structured JSON messages. For PR_MERGED events, it also updates
Task.pr_merged in the database.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType
from src.shared.config import settings

logger = logging.getLogger(__name__)

# GitHub check-run conclusions that indicate an actionable CI failure.
# Conclusions not in this set — including null (pending), "success", "neutral",
# and "skipped" — must not trigger a ci_failed notification.
# See: https://docs.github.com/en/rest/checks/runs#get-a-check-run
CI_FAILED_CONCLUSIONS = frozenset({"failure", "cancelled", "timed_out", "action_required", "stale"})

# Event types that may be routed to the main agent inbox when no worktree
# resolves. ISSUE_COMMENT is intentionally excluded — bots generate heavy
# noise on that event and the main agent should not receive it.
MAIN_AGENT_EVENTS = frozenset(
    {
        WebhookEventType.PR_MERGED,
        WebhookEventType.PR_CLOSED,
        WebhookEventType.REVIEW_SUBMITTED,
        WebhookEventType.REVIEW_COMMENT,
        WebhookEventType.CHECK_RUN_COMPLETED,
    }
)


@dataclass(frozen=True)
class ResolvedRecipient:
    """Resolved destination for a webhook event.

    When ``worktree_id`` is None the recipient is the main agent inbox,
    not a regular worktree agent.
    """

    inbox_path: Path
    worktree_id: UUID | None


class AgentNotifierConsumer:
    """Route PR events to the owning worktree agent via inbox file."""

    _handled = {
        WebhookEventType.PR_OPENED,
        WebhookEventType.PR_SYNCHRONIZE,
        WebhookEventType.PR_MERGED,
        WebhookEventType.PR_CLOSED,
        WebhookEventType.REVIEW_SUBMITTED,
        WebhookEventType.REVIEW_COMMENT,
        WebhookEventType.ISSUE_COMMENT,
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
            result = await self._resolve_agent(event, session)

            # For PR_MERGED, update the task's pr_merged flag regardless of agent status
            if event.type == WebhookEventType.PR_MERGED:
                await self._mark_pr_merged(event.pr_url, session)

            # Update pr_head_sha on the task so the board can project codex
            # status without fetching from GitHub (T-409). Scoped by project
            # via repo_full_name so two projects sharing the same PR URL cannot
            # overwrite each other's head SHA.
            if event.type in (WebhookEventType.PR_OPENED, WebhookEventType.PR_SYNCHRONIZE):
                head_sha = (event.raw.get("pull_request") or {}).get("head", {}).get("sha", "")
                if head_sha:
                    await self._update_pr_head_sha(
                        event.pr_url, head_sha, event.repo_full_name, session
                    )

            if result is None:
                # _resolve_agent already logged the specific drop reason
                # (T-305); this debug line keeps the per-event trace.
                logger.debug("No agent found for PR %s", event.pr_url)
                return

            # Build message based on event type
            message = self._build_message(event)
            if message is None:
                return

            inbox_path = result.inbox_path
            inbox_path.parent.mkdir(parents=True, exist_ok=True)
            with inbox_path.open("a") as f:
                f.write(json.dumps(message) + "\n")
            logger.info(
                "Notified agent %s of %s on PR #%d",
                result.worktree_id,
                event.type,
                event.pr_number,
            )

    async def _resolve_agent(
        self, event: WebhookEvent, session: AsyncSession
    ) -> ResolvedRecipient | None:
        """Resolve PR event to owning worktree or main-agent inbox.

        Primary: match Task.pr_url → worktree_id → Worktree.worktree_path.
        Secondary: match Worktree.branch_name (for PRs opened before agent sets pr_url).
        Tertiary (T-245): route to the project's main-agent worktree
          (``worktrees.role='main'``) for eligible event types. Handles close-wave
          and main-agent-authored PRs whose branch has no registered worktree row,
          so they reach the main agent instead of being silently dropped.
        Quaternary (T-253 compatibility): when no main-agent worktree is
          registered yet but ``settings.main_agent_inbox_path`` is configured,
          fall back to that file path. This preserves the documented deployment
          contract from before T-245 — operators who have set the env var but
          have not yet run ``/cloglog setup`` (which registers the main agent)
          still receive unmatched PR events instead of having them dropped.

        ISSUE_COMMENT is excluded from the main-agent fallbacks because bots
        generate heavy noise on that event type.

        Returns ResolvedRecipient or None.
        """
        from src.agent.repository import AgentRepository
        from src.board.repository import BoardRepository

        repo = BoardRepository(session)
        agent_repo = AgentRepository(session)

        # Primary: match by pr_url
        task = await repo.find_task_by_pr_url(event.pr_url)
        if task is not None and task.worktree_id is not None:
            worktree = await agent_repo.get_worktree(task.worktree_id)
            if worktree is not None:
                inbox_path = Path(worktree.worktree_path) / ".cloglog" / "inbox"
                return ResolvedRecipient(inbox_path=inbox_path, worktree_id=worktree.id)

        # Both the branch-name fallback and the main-agent fallback require the
        # event's repo to be a configured cloglog project. Gating on this also
        # defends the main-agent inbox against valid signed webhooks from repos
        # that happen to share this backend's webhook endpoint/secret but are
        # NOT this cloglog project — without the guard, a foreign repo's PR
        # merge could land in our main-agent inbox simply because the primary
        # pr_url lookup missed.
        project = await repo.find_project_by_repo(event.repo_full_name)
        if project is None:
            # T-305: silent drops for unmatched PRs were impossible to diagnose
            # in production (PR #231, 2026-04-26: codex review never reached
            # the main inbox; root cause invisible without this log line).
            logger.warning(
                "Webhook drop: no cloglog project matches repo %s (event=%s pr=%s)",
                event.repo_full_name,
                event.type,
                event.pr_url,
            )
            return None

        # Secondary: match by branch name. Issue-comment webhooks don't carry
        # a head_branch the way PR events do, so skip the branch lookup when
        # it's empty — otherwise an equality match on '' would fan out across
        # every online worktree (many have legacy empty branch_name rows) and
        # raise MultipleResultsFound.
        if event.head_branch:
            worktree = await agent_repo.get_worktree_by_branch(project.id, event.head_branch)
            if worktree is not None:
                inbox_path = Path(worktree.worktree_path) / ".cloglog" / "inbox"
                return ResolvedRecipient(inbox_path=inbox_path, worktree_id=worktree.id)

        # Tertiary (T-245): fall back to the project's main-agent worktree.
        # ISSUE_COMMENT is excluded to avoid bot-comment spam in the main inbox.
        if event.type in MAIN_AGENT_EVENTS:
            main_worktree = await agent_repo.get_main_agent_worktree(project.id)
            if main_worktree is not None:
                inbox_path = Path(main_worktree.worktree_path) / ".cloglog" / "inbox"
                return ResolvedRecipient(inbox_path=inbox_path, worktree_id=main_worktree.id)

            # Quaternary (T-253 compat): the role-based lookup is the source of
            # truth, but the documented MAIN_AGENT_INBOX_PATH env var still has
            # to work for operators who set it before running /cloglog setup —
            # otherwise this PR is a silent regression for that deployment path.
            if settings.main_agent_inbox_path is not None:
                return ResolvedRecipient(
                    inbox_path=settings.main_agent_inbox_path, worktree_id=None
                )

            # T-305: both T-245 (role='main') and T-253 (env-var compat)
            # fallbacks missed — this is the silent-drop signature seen on
            # PR #231. Surface it as a warning so the operator can backfill
            # the role or set MAIN_AGENT_INBOX_PATH instead of guessing.
            logger.warning(
                "Webhook drop: project %s has no role='main' worktree and "
                "main_agent_inbox_path is unset (event=%s pr=%s repo=%s)",
                project.id,
                event.type,
                event.pr_url,
                event.repo_full_name,
            )
            return None

        # ISSUE_COMMENT (or any non-main-agent event) with no branch/pr_url
        # match: deliberate drop, but log at debug so it stays out of warning
        # noise while remaining traceable when inspecting backend logs.
        logger.debug(
            "Webhook drop: no recipient for event=%s pr=%s repo=%s "
            "(non-main-agent event with no branch/pr_url match)",
            event.type,
            event.pr_url,
            event.repo_full_name,
        )
        return None

    async def _mark_pr_merged(self, pr_url: str, session: AsyncSession) -> None:
        """Update Task.pr_merged = True for the task matching this PR URL."""
        from src.board.repository import BoardRepository

        repo = BoardRepository(session)
        task = await repo.find_task_by_pr_url(pr_url)
        if task is not None:
            await repo.update_task(task.id, pr_merged=True)
            logger.info("Marked task %s pr_merged=True for %s", task.id, pr_url)

    async def _update_pr_head_sha(
        self, pr_url: str, head_sha: str, repo_full_name: str, session: AsyncSession
    ) -> None:
        """Store the current head SHA on the task for codex status projection (T-409).

        Scoped to the project that owns repo_full_name so two projects sharing
        the same PR URL cannot overwrite each other's head SHA.
        """
        from src.board.repository import BoardRepository

        repo = BoardRepository(session)
        project = await repo.find_project_by_repo(repo_full_name)
        if project is None:
            logger.debug("pr_head_sha update skipped: no project for repo %s", repo_full_name)
            return
        task = await repo.find_task_by_pr_url_for_project(pr_url, project.id)
        if task is not None:
            await repo.update_task(task.id, pr_head_sha=head_sha)
            logger.debug("Updated pr_head_sha=%s for task %s (%s)", head_sha[:7], task.id, pr_url)

    def _build_message(self, event: WebhookEvent) -> dict[str, Any] | None:
        if event.type == WebhookEventType.PR_MERGED:
            return {
                "type": "pr_merged",
                "pr_url": event.pr_url,
                "pr_number": event.pr_number,
                "message": (
                    f"PR #{event.pr_number} has been MERGED. "
                    "Run the per-task shutdown sequence: "
                    "(1) emit pr_merged_notification to the main inbox, "
                    "(2) call mark_pr_merged, "
                    "(3) for spec/plan tasks call report_artifact, "
                    "(4) write shutdown-artifacts/work-log-T-<NNN>.md, "
                    "(5) build aggregate shutdown-artifacts/work-log.md, "
                    "(6) emit agent_unregistered with reason='pr_merged', "
                    "(7) call unregister_agent and exit. "
                    "Do NOT call get_my_tasks or start the next task — "
                    "the supervisor handles relaunching."
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
        if event.type == WebhookEventType.REVIEW_COMMENT:
            comment = event.raw.get("comment", {})
            body = (comment.get("body") or "")[:500]
            path = comment.get("path", "")
            line = comment.get("line") or comment.get("original_line", "")
            return {
                "type": "review_comment",
                "pr_url": event.pr_url,
                "pr_number": event.pr_number,
                "reviewer": event.sender,
                "path": path,
                "line": line,
                "body": body,
                "message": (
                    f"Inline comment on PR #{event.pr_number} by {event.sender}"
                    + (f" at {path}:{line}" if path else "")
                    + f": {body}"
                ),
            }
        if event.type == WebhookEventType.ISSUE_COMMENT:
            comment = event.raw.get("comment", {})
            body = (comment.get("body") or "")[:500]
            return {
                "type": "issue_comment",
                "pr_url": event.pr_url,
                "pr_number": event.pr_number,
                "commenter": event.sender,
                "body": body,
                "message": (f"Comment on PR #{event.pr_number} by {event.sender}: {body}"),
            }
        if event.type == WebhookEventType.CHECK_RUN_COMPLETED:
            check = event.raw.get("check_run", {})
            conclusion = check.get("conclusion")
            name = check.get("name", "")
            # GitHub fires check_run events before the check terminates; at that
            # point conclusion is null. Only notify on terminal non-success
            # conclusions we can act on — silently skip everything else.
            if conclusion not in CI_FAILED_CONCLUSIONS:
                return None
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


async def emit_codex_review_timed_out(
    *,
    pr_url: str,
    pr_number: int,
    repo_full_name: str,
    head_branch: str,
    diff_size: int,
    timeout_seconds: float,
    session_factory: Any | None = None,
) -> None:
    """Append a ``codex_review_timed_out`` event to the project's main-agent inbox.

    T-374 (codex round 3 HIGH + MEDIUM): the supervisor watches
    ``<PROJECT_ROOT>/.cloglog/inbox`` (see ``docs/invariants.md`` §
    supervisor inbox), and the inbound contract for *worktree* inboxes
    (`docs/design/agent-lifecycle.md`, `plugins/cloglog/skills/github-bot/SKILL.md`,
    `plugins/cloglog/agents/worktree-agent.md`) enumerates a closed
    set of event types: ``review_submitted``, ``review_comment``,
    ``issue_comment``, ``ci_failed``, ``pr_merged``, ``pr_closed``.
    Adding a new event type to a worktree inbox without expanding
    that contract leaves no documented handler, so the signal sits
    unread.

    The supervisor inbox is the right destination — it is the same
    destination family as ``pr_merged_notification`` and
    ``agent_unregistered``, both of which are cross-worktree signals
    the supervisor already reacts to. The main-agent inbox path is
    resolved exactly the way ``AgentNotifierConsumer._resolve_agent``
    resolves it for unmatched PR events: project's role='main'
    worktree first, then ``settings.main_agent_inbox_path`` as the
    documented compat fallback.

    ``head_branch`` is currently unused — main-inbox routing keys on
    project, not on the PR's branch. The parameter is kept so a
    future variant that fans out to both the worktree inbox AND the
    main inbox can use it without a signature break.
    """
    from src.agent.repository import AgentRepository
    from src.board.repository import BoardRepository
    from src.shared.database import async_session_factory

    del head_branch  # see docstring — main-inbox routing is project-scoped.

    factory = session_factory or async_session_factory
    inbox_path: Path | None = None
    try:
        async with factory() as session:
            board_repo = BoardRepository(session)
            project = await board_repo.find_project_by_repo(repo_full_name)
            # T-374 codex round 5 HIGH: gate ALL main-inbox routing on
            # the repo being a known cloglog project. The legacy env-var
            # fallback (``settings.main_agent_inbox_path``) is a
            # compat path for **known projects** that have not yet
            # registered a role='main' worktree — it must NOT be used
            # for unknown repos. Without this guard, a signed webhook
            # from a foreign repo sharing the endpoint/secret could
            # leak ``codex_review_timed_out`` into THIS project's
            # supervisor inbox, the exact cross-repo leak
            # ``_resolve_agent`` was written to block.
            if project is None:
                logger.warning(
                    "codex_review_timed_out: no cloglog project matches repo=%s "
                    "(pr=%s) — dropping (env-var fallback is gated on a known repo)",
                    repo_full_name,
                    pr_url,
                )
                return
            agent_repo = AgentRepository(session)
            main_worktree = await agent_repo.get_main_agent_worktree(project.id)
            if main_worktree is not None:
                inbox_path = Path(main_worktree.worktree_path) / ".cloglog" / "inbox"
        if inbox_path is None and settings.main_agent_inbox_path is not None:
            # T-253 compat — operators that set the env var but have not
            # yet run ``/cloglog setup`` (which registers the role='main'
            # worktree) still get the signal. Only reachable when the
            # project lookup above succeeded.
            inbox_path = settings.main_agent_inbox_path
    except Exception as err:  # noqa: BLE001 - best-effort signal, never raise into the loop
        logger.warning(
            "codex_review_timed_out: main-inbox resolution failed for pr=%s (%s) — dropping",
            pr_url,
            err,
        )
        return
    if inbox_path is None:
        logger.warning(
            "codex_review_timed_out: no main-agent inbox for repo=%s pr=%s — dropping. "
            "Register a role='main' worktree (run /cloglog setup) or set "
            "MAIN_AGENT_INBOX_PATH to capture supervisor signals.",
            repo_full_name,
            pr_url,
        )
        return
    payload = {
        "type": "codex_review_timed_out",
        "pr_url": pr_url,
        "pr_number": pr_number,
        "repo_full_name": repo_full_name,
        "diff_size": diff_size,
        "timeout_seconds": timeout_seconds,
        "ts": datetime.now(UTC).isoformat(),
        "message": (
            f"Codex review on PR #{pr_number} timed out after "
            f"{int(timeout_seconds)}s ({diff_size} changed lines). "
            "Push a new commit to retry."
        ),
    }
    try:
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        with inbox_path.open("a") as f:
            f.write(json.dumps(payload) + "\n")
    except OSError as err:
        logger.warning(
            "codex_review_timed_out: could not append to %s (%s) — dropping",
            inbox_path,
            err,
        )
        return
    logger.info(
        "codex_review_timed_out: appended to main inbox %s for PR #%d (%d lines, %.0fs)",
        inbox_path,
        pr_number,
        diff_size,
        timeout_seconds,
    )
