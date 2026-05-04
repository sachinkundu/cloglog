"""Business logic for the Agent bounded context."""

from __future__ import annotations

import hashlib
import logging
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.exceptions import TaskBlockedError
from src.agent.interfaces import BlockerDTO, IWorktreeQuery, PipelineBlocker, WorktreeRow
from src.agent.repository import AgentRepository
from src.board.interfaces import BoardBlockerQueryPort
from src.board.models import Task
from src.board.repository import BoardRepository
from src.shared.config import settings
from src.shared.events import Event, EventType, event_bus

logger = logging.getLogger(__name__)

# Path segment that distinguishes a sandboxed worktree checkout from the
# project's repo-root (main agent) checkout. T-245: the webhook resolver
# uses ``worktrees.role`` to fall back to the main-agent inbox; the role
# is derived from this segment at registration time so no separate config
# or project.repo_root field is needed.
_WORKTREE_PATH_MARKER = "/.claude/worktrees/"


def _derive_worktree_role(worktree_path: str) -> str:
    return "worktree" if _WORKTREE_PATH_MARKER in worktree_path else "main"


def make_worktree_query(session: AsyncSession) -> IWorktreeQuery:
    """Build an ``IWorktreeQuery`` bound to an open async session.

    Open Host Service boundary between Agent and Gateway: callers get the
    Protocol-typed instance and never see ``AgentRepository`` or
    ``src.agent.models``. Mirrors ``make_review_turn_registry`` in the
    Review context. T-278 shipped ``find_by_branch``; T-281 adds
    ``find_by_pr_url`` which composes Board + Agent repositories inside
    the adapter so neither layer learns about the other's models.
    """
    return _WorktreeQueryAdapter(AgentRepository(session), BoardRepository(session))


class _WorktreeQueryAdapter:
    """Thin ORM-to-DTO adapter implementing ``IWorktreeQuery``.

    Keeps the ORM row inside the Agent context — callers receive a frozen
    ``WorktreeRow`` with just the fields Gateway consumers need. The
    ``find_by_pr_url`` path composes ``BoardRepository`` (for the
    ``tasks.pr_url → task.worktree_id`` lookup) and ``AgentRepository``
    (for the final ``worktrees.id`` row) so neither repository has to
    import the other's models — the join lives at the adapter seam.
    """

    def __init__(self, repo: AgentRepository, board_repo: BoardRepository) -> None:
        self._repo = repo
        self._board_repo = board_repo

    async def find_by_branch(self, project_id: UUID, branch_name: str) -> WorktreeRow | None:
        worktree = await self._repo.find_worktree_by_branch_any_status(project_id, branch_name)
        if worktree is None:
            return None
        return WorktreeRow(
            id=worktree.id,
            project_id=worktree.project_id,
            worktree_path=worktree.worktree_path,
            branch_name=worktree.branch_name,
            status=worktree.status,
        )

    async def find_by_pr_url(self, project_id: UUID, pr_url: str) -> WorktreeRow | None:
        if not pr_url:
            return None
        task = await self._board_repo.find_task_by_pr_url_for_project(pr_url, project_id)
        if task is None or task.worktree_id is None:
            return None
        worktree = await self._repo.get_worktree(task.worktree_id)
        if worktree is None:
            return None
        return WorktreeRow(
            id=worktree.id,
            project_id=worktree.project_id,
            worktree_path=worktree.worktree_path,
            branch_name=worktree.branch_name,
            status=worktree.status,
        )


class AgentService:
    def __init__(
        self,
        repo: AgentRepository,
        board_repo: BoardRepository,
        board_blockers: BoardBlockerQueryPort | None = None,
    ) -> None:
        """Agent service.

        ``board_blockers`` is the port Agent calls to ask Board 'what's
        blocking this task?'. It is optional so that legacy callers (and
        code paths that never exercise ``start_task`` / ``update_task_status``
        with a target of ``in_progress``) don't have to supply it. When the
        guard needs it and it is ``None``, we lazily construct a
        ``BoardService`` over the same repository — this matches what every
        call site would do anyway and avoids repeating the wiring at every
        construction site.
        """
        self._repo = repo
        self._board_repo = board_repo
        self._board_blockers = board_blockers

    def _blocker_query(self) -> BoardBlockerQueryPort:
        """Resolve the blocker-query port, lazy-constructing if needed.

        We import ``BoardService`` locally to avoid a module-level import
        cycle (``board.services`` imports from ``board.models`` etc., and
        Agent already imports from Board — keeping this lazy keeps import
        order agnostic).
        """
        if self._board_blockers is not None:
            return self._board_blockers
        from src.board.services import BoardService

        return BoardService(self._board_repo)

    # --- Registration ---

    async def register(
        self, project_id: UUID, worktree_path: str, branch_name: str
    ) -> dict[str, object]:
        """Register or reconnect a worktree. Returns registration info.

        ``branch_name`` is supplied by the caller rather than probed from the
        filesystem here: the caller (the MCP server or a direct API client)
        is already in the worktree and knows the branch, and keeping the
        backend a pure CRUD layer avoids an unnecessary ``git`` subprocess
        on every registration. The webhook resolver's empty-``head_branch``
        short-circuit and ``get_worktree_by_branch``'s empty-guard are the
        safety nets if a caller sends an empty value.
        """
        worktree, is_new = await self._repo.upsert_worktree(
            project_id, worktree_path, branch_name, role=_derive_worktree_role(worktree_path)
        )

        # Always generate a fresh agent token on registration.
        # The previous session's MCP server process is gone, so the old
        # token is unreachable — rotating is safe and necessary for the
        # new caller to authenticate heartbeats and agent-scoped requests.
        agent_token = _uuid.uuid4().hex
        token_hash = hashlib.sha256(agent_token.encode()).hexdigest()
        await self._repo.set_agent_token_hash(worktree.id, token_hash)

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
                    "number": task.number,
                    "title": task.title,
                    "description": task.description,
                    "status": task.status,
                    "priority": task.priority,
                    "pr_url": task.pr_url,
                    "artifact_path": task.artifact_path,
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
            "project_id": project_id,
            "current_task": current_task,
            "resumed": not is_new,
            "agent_token": agent_token,
        }

    # --- Shutdown ---

    async def request_shutdown(self, worktree_id: UUID) -> None:
        """Request agent shutdown via the worktree inbox.

        Writes a shutdown JSON line to ``<worktree_path>/.cloglog/inbox`` —
        the same file the webhook consumer writes to and the worktree agent
        tails. See ``docs/design/agent-lifecycle.md`` section 3 for the
        canonical inbox contract.
        """
        import json
        from pathlib import Path

        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        if not worktree.worktree_path:
            raise ValueError(
                f"Worktree {worktree_id} has no worktree_path; cannot deliver shutdown signal"
            )

        inbox_path = Path(worktree.worktree_path) / ".cloglog" / "inbox"
        message = json.dumps(
            {
                "type": "shutdown",
                "message": (
                    "SHUTDOWN REQUESTED: The master agent has requested this worktree "
                    "to shut down. Finish your current work, write the per-task "
                    "shutdown-artifacts/work-log-T-<NNN>.md, build the aggregate "
                    "shutdown-artifacts/work-log.md, emit agent_unregistered to the "
                    "main inbox, call unregister_agent, and exit."
                ),
            }
        )
        try:
            inbox_path.parent.mkdir(parents=True, exist_ok=True)
            with inbox_path.open("a") as f:
                f.write(message + "\n")
        except OSError as exc:
            raise OSError(f"Failed to write shutdown signal to {inbox_path}: {exc}") from exc

        # DB flag stays as a secondary signal for agents not on Monitor.
        await self._repo.request_shutdown(worktree_id)

    # --- Heartbeat ---

    async def heartbeat(self, worktree_id: UUID) -> dict[str, object]:
        """Update heartbeat for the active session of a worktree."""
        session = await self._repo.get_active_session(worktree_id)
        if session is None:
            raise ValueError(f"No active session for worktree {worktree_id}")

        updated = await self._repo.update_heartbeat(session.id)
        assert updated is not None

        return {
            "status": "ok",
            "last_heartbeat": updated.last_heartbeat,
        }

    # --- Task Assignment ---

    async def assign_task(self, worktree_id: UUID, task_id: UUID) -> dict[str, object]:
        """Assign a task to a worktree without changing its status.

        Sets worktree_id on the task so it appears in get_my_tasks for the agent.
        Also sends a message to the target agent notifying it of the assignment.
        """
        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        task = await self._board_repo.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        await self._board_repo.update_task(task_id, worktree_id=worktree_id)

        await event_bus.publish(
            Event(
                type=EventType.TASK_STATUS_CHANGED,
                project_id=worktree.project_id,
                data={
                    "task_id": str(task_id),
                    "worktree_id": str(worktree_id),
                    "action": "assigned",
                },
            )
        )

        return {"task_id": task_id, "worktree_id": worktree_id, "status": "assigned"}

    # --- Task Lifecycle ---

    async def _collect_all_blockers(self, task: Task) -> list[BlockerDTO]:
        """Ask Board for feature/task blockers and splice in pipeline ones.

        Stable order: ``feature → task → pipeline``. Pipeline entries come
        last so the "broad → narrow" progression matches the spec's guard
        order and what the tests assert on.
        """
        board_blockers = await self._blocker_query().get_unresolved_blockers(task.id)
        feature_tasks = await self._board_repo.get_tasks_for_feature(task.feature_id)
        pipeline_blockers = self._collect_pipeline_blockers(task, feature_tasks)
        return [*board_blockers, *pipeline_blockers]

    def _collect_pipeline_blockers(
        self, task: Task, feature_tasks: list[Task]
    ) -> list[PipelineBlocker]:
        """Return pipeline-predecessor blockers for ``task``.

        Returns ``[]`` when the pipeline is satisfied. Does **not** raise —
        callers (``start_task`` and ``update_task_status``) combine the
        result with Board-provided blockers before deciding to raise.

        Semantics (unchanged from the prior ``_check_pipeline_predecessors``):
        a predecessor counts as completed when ``done`` OR (``review`` with
        ``pr_url`` AND — for ``spec``/``plan`` predecessors — an attached
        artifact). The artifact check is specific to pipeline blockers;
        arbitrary task-level ``blocked_by`` edges do not require it.
        """
        if task.task_type == "task":
            return []

        predecessor_type: str | None = None
        if task.task_type == "plan":
            predecessor_type = "spec"
        elif task.task_type == "impl":
            predecessor_type = "plan"

        if predecessor_type is None:
            return []

        predecessors = [t for t in feature_tasks if t.task_type == predecessor_type]
        if not predecessors:
            return []

        def _pipeline_resolved(t: Task) -> bool:
            if t.status == "done":
                return True
            if t.status == "review" and bool(t.pr_url):
                return not (t.task_type in ("spec", "plan") and not t.artifact_path)
            return False

        blockers: list[PipelineBlocker] = []
        for p in sorted(predecessors, key=lambda t: t.number):
            if _pipeline_resolved(p):
                continue
            reason: str = (
                "artifact_missing"
                if (p.status == "review" and bool(p.pr_url) and not p.artifact_path)
                else "not_done"
            )
            blockers.append(
                PipelineBlocker(
                    kind="pipeline",
                    predecessor_task_type=predecessor_type,
                    task_id=str(p.id),
                    task_number=p.number,
                    task_title=p.title,
                    status=p.status,
                    reason=reason,  # type: ignore[typeddict-item]
                )
            )
        return blockers

    async def start_task(self, worktree_id: UUID, task_id: UUID) -> dict[str, object]:
        """Start working on a task."""
        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        task = await self._board_repo.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        # Guard: one active task per agent — reject if already working on something.
        # Tasks in review with a merged PR are considered finished (agent is free).
        existing_tasks = await self._board_repo.get_tasks_for_worktree(worktree_id)
        active = [
            t
            for t in existing_tasks
            if t.id != task_id and t.status in ("in_progress", "review") and not t.pr_merged
        ]
        if active:
            titles = ", ".join(f"T-{t.number} '{t.title}' ({t.status})" for t in active)
            raise ValueError(
                f"Cannot start task: agent already has active task(s): {titles}. "
                f"Finish or move the current task before starting a new one."
            )

        # Guard: collect all blockers (feature deps + pipeline ordering).
        # Raise a single TaskBlockedError so the route layer can emit a
        # structured 409 payload (code=task_blocked, blockers=[...]).
        blockers = await self._collect_all_blockers(task)
        if blockers:
            raise TaskBlockedError(task, blockers)

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

        return {"task_id": task_id, "status": "in_progress", "model": task.model}

    async def complete_task(
        self, worktree_id: UUID, task_id: UUID, pr_url: str | None = None
    ) -> dict[str, object]:
        """Complete a task and return the next assigned task if any."""
        raise ValueError(
            "Agents cannot mark tasks as done. "
            "Move the task to 'review' and wait for the user to mark it done "
            "by dragging the card on the board."
        )

        # --- Dead code below: kept for reference when user-done is removed ---
        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        task = await self._board_repo.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        # Guard: spec and impl tasks require PR to be in review before completing
        if task.task_type in ("spec", "impl") and task.status != "review":
            raise ValueError(
                f"Cannot complete {task.task_type} task: "
                f"must be in 'review' status first "
                f"(current: {task.status}). "
                f"Move to review with a PR URL first."
            )

        # Guard: pr_url must not be reused by another done task in same feature
        if pr_url:
            feature_tasks = await self._board_repo.get_tasks_for_feature(task.feature_id)
            for ft in feature_tasks:
                if ft.id != task.id and ft.pr_url == pr_url and ft.status == "done":
                    raise ValueError(
                        f"PR {pr_url} is already used by completed task "
                        f"T-{ft.number} ({ft.title}). "
                        f"Create a new PR for this task."
                    )

        # Update pr_url if provided
        update_fields: dict[str, object] = {"status": "done"}
        if pr_url is not None:
            update_fields["pr_url"] = pr_url

        # Mark task done
        await self._board_repo.update_task(task_id, **update_fields)
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
                    "number": t.number,
                    "title": t.title,
                    "description": t.description,
                    "status": t.status,
                    "priority": t.priority,
                    "pr_url": t.pr_url,
                    "artifact_path": t.artifact_path,
                }
                break

        return {"completed_task_id": task_id, "next_task": next_task}

    async def update_task_status(
        self,
        worktree_id: UUID,
        task_id: UUID,
        status: str,
        pr_url: str | None = None,
        skip_pr: bool = False,
    ) -> None:
        """Update a task's status (e.g. to review, blocked)."""
        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        task = await self._board_repo.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        # Guard: agents cannot move tasks to done — only user can via board UI.
        # Exception A: close-off tasks with close_off_worktree_id set may be marked done
        # by the close-wave supervisor after the direct-to-main commit (T-395).
        # Exception B: legacy stale close-off rows whose close_off_worktree_id was
        # cleared by ON DELETE SET NULL when the worktree was torn down. These rows
        # are identifiable by their canonical title prefix; reconcile auto-fixes them.
        # Pin: test_unit.py::TestAgentService::test_close_off_task_can_be_marked_done_by_agent
        is_close_off_task = task.close_off_worktree_id is not None or task.title.startswith(
            "Close worktree "
        )
        if status == "done" and not is_close_off_task:
            raise ValueError(
                "Agents cannot mark tasks as done. "
                "Move the task to 'review' and wait for the user "
                "to drag it to done on the board."
            )

        # Guard: transitioning into in_progress runs the same blocker pass
        # as start_task, so agents cannot bypass it by PATCH-ing status.
        if status == "in_progress":
            blockers = await self._collect_all_blockers(task)
            if blockers:
                raise TaskBlockedError(task, blockers)

        # Guard: moving to review requires pr_url unless skip_pr is set
        if status == "review" and not pr_url and not task.pr_url and not skip_pr:
            raise ValueError(
                "Cannot move task to review without a PR URL. "
                "Provide pr_url parameter with the GitHub PR link. "
                "If this task has zero source code changes (no .py/.ts/.tsx/.js files modified), "
                "set skip_pr=true instead."
            )

        # Guard: pr_url must not be reused by another done task in same feature
        if pr_url and status == "review":
            feature_tasks = await self._board_repo.get_tasks_for_feature(task.feature_id)
            for ft in feature_tasks:
                if ft.id != task.id and ft.pr_url == pr_url and ft.status == "done":
                    raise ValueError(
                        f"PR {pr_url} is already used by completed task "
                        f"T-{ft.number} ({ft.title}). "
                        f"Create a new PR for this task."
                    )

        # Guard: moving to done requires the task to have been in review (for spec/impl)
        if status == "done" and task.task_type in ("spec", "impl") and task.status != "review":
            raise ValueError(
                f"Cannot move {task.task_type} task directly to done. "
                f"It must go through review first."
            )

        update_fields: dict[str, object] = {"status": status}
        if pr_url is not None:
            update_fields["pr_url"] = pr_url

        await self._board_repo.update_task(task_id, **update_fields)

        if status == "done":
            # Recompute parent roll-ups so the board reflects the completed task.
            from src.board.services import BoardService

            await BoardService(self._board_repo).recompute_rollup(task.feature_id)
            # Clear the worktree's current_task_id so the supervisor doesn't
            # resume with a stale pointer to this already-done task.
            if worktree.current_task_id == task_id:
                await self._repo.set_worktree_current_task(worktree_id, None)

        await event_bus.publish(
            Event(
                type=EventType.TASK_STATUS_CHANGED,
                project_id=worktree.project_id,
                data={
                    "task_id": str(task_id),
                    "worktree_id": str(worktree_id),
                    "new_status": status,
                },
            )
        )

    async def mark_pr_merged(self, worktree_id: UUID, task_id: UUID) -> dict[str, object]:
        """Set pr_merged=True on the specified task.

        Called by agents when the polling loop detects a merge, as a fallback
        when the GitHub webhook hasn't fired (or isn't configured). Accepts
        task_id directly to avoid any pr_url uniqueness ambiguity.

        Verifies the task belongs to the caller's project to prevent
        cross-project manipulation.
        """
        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        task = await self._board_repo.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        # Verify ownership — task must belong to the caller's project
        feature = await self._board_repo.get_feature(task.feature_id)
        if feature is None:
            raise ValueError(f"Feature not found for task {task_id}")
        epic = await self._board_repo.get_epic(feature.epic_id)
        if epic is None or epic.project_id != worktree.project_id:
            raise ValueError(f"Task {task_id} does not belong to this agent's project")

        await self._board_repo.update_task(task_id, pr_merged=True)
        logger.info("Marked task %s pr_merged=True via polling", task_id)
        return {"task_id": str(task_id), "pr_merged": True}

    # --- Artifact Reporting ---

    async def report_artifact(
        self, worktree_id: UUID, task_id: UUID, artifact_path: str
    ) -> dict[str, object]:
        """Attach an artifact path to a spec or plan task and create a Document record."""
        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        task = await self._board_repo.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        if task.task_type not in ("spec", "plan"):
            raise ValueError(
                f"Cannot attach artifact to {task.task_type} task: "
                f"only spec and plan tasks produce artifacts"
            )

        if task.status != "review":
            raise ValueError(
                f"Cannot attach artifact: task must be in 'review' status (current: {task.status})"
            )

        await self._board_repo.update_task(task_id, artifact_path=artifact_path)

        # Create a Document record attached to the feature
        from src.document.repository import DocumentRepository

        doc_repo = DocumentRepository(self._board_repo._session)
        await doc_repo.create_document(
            title=f"{task.task_type} — {task.title}",
            content="",
            doc_type=task.task_type,
            source_path=artifact_path,
            attached_to_type="feature",
            attached_to_id=task.feature_id,
        )

        await event_bus.publish(
            Event(
                type=EventType.TASK_STATUS_CHANGED,
                project_id=worktree.project_id,
                data={
                    "task_id": str(task_id),
                    "worktree_id": str(worktree_id),
                    "action": "artifact_attached",
                    "artifact_path": artifact_path,
                },
            )
        )

        return {
            "task_id": task_id,
            "artifact_path": artifact_path,
            "feature_id": task.feature_id,
        }

    # --- Unregister ---

    async def unregister(
        self, worktree_id: UUID, artifacts: dict[str, str | None] | None = None
    ) -> None:
        """End the active session and delete worktree record.

        Publishes both ``WORKTREE_OFFLINE`` (legacy) and ``AGENT_UNREGISTERED``
        (T-358 desktop-toast dispatcher input). The latter carries no
        ``reason`` here -- callers that go through the public unregister API
        are clean shutdowns by definition. ``force_unregister`` and the
        heartbeat-timeout sweep set ``reason`` explicitly and the toast
        dispatcher fires only on those known-non-clean values.
        """
        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        session = await self._repo.get_active_session(worktree_id)
        if session is not None:
            await self._repo.end_session(session.id)

        event_data: dict[str, object] = {
            "worktree_id": str(worktree_id),
            "worktree_path": worktree.worktree_path,
        }
        if artifacts is not None:
            event_data["artifacts"] = artifacts

        await event_bus.publish(
            Event(
                type=EventType.WORKTREE_OFFLINE,
                project_id=worktree.project_id,
                data=event_data,
            )
        )
        await event_bus.publish(
            Event(
                type=EventType.AGENT_UNREGISTERED,
                project_id=worktree.project_id,
                data=event_data,
            )
        )

        await self._repo.delete_worktree(worktree_id)

    async def force_unregister(
        self,
        worktree_id: UUID,
        caller_project_id: UUID | None,
    ) -> dict[str, object]:
        """Supervisor-initiated unregistration of a (possibly wedged) worktree.

        Tier-2 fallback in the agent-lifecycle protocol — the supervisor
        calls ``request_shutdown`` first and gives the agent a grace period;
        only when that times out does ``force_unregister`` run. See
        ``docs/design/agent-lifecycle.md`` for the full sequence.

        Idempotent: if the worktree is already gone, returns
        ``{"already_unregistered": true, ...}`` with no state change and no
        second ``WORKTREE_OFFLINE`` event.

        ``caller_project_id`` is ``None`` for MCP-service-key callers; when
        set, we refuse to cross project boundaries (we can't tell whether a
        missing worktree used to belong to a different project, so the "gone
        and idempotent" response is the same either way — the audit log
        records which project actually forced the action).
        """
        worktree = await self._repo.get_worktree(worktree_id)
        already_unregistered = worktree is None

        if worktree is not None:
            if caller_project_id is not None and worktree.project_id != caller_project_id:
                raise PermissionError(
                    f"Worktree {worktree_id} does not belong to project {caller_project_id}"
                )

            session = await self._repo.get_active_session(worktree_id)
            if session is not None:
                await self._repo.end_session(session.id, status="force_unregistered")

            offline_data = {
                "worktree_id": str(worktree_id),
                "worktree_path": worktree.worktree_path,
                "reason": "force_unregistered",
                "caller_project_id": (
                    str(caller_project_id) if caller_project_id else "mcp_service"
                ),
            }
            await event_bus.publish(
                Event(
                    type=EventType.WORKTREE_OFFLINE,
                    project_id=worktree.project_id,
                    data=offline_data,
                )
            )
            # T-358: also surface as AGENT_UNREGISTERED so the desktop-toast
            # dispatcher fires (force_unregistered is non-clean by definition).
            await event_bus.publish(
                Event(
                    type=EventType.AGENT_UNREGISTERED,
                    project_id=worktree.project_id,
                    data=offline_data,
                )
            )

            await self._repo.delete_worktree(worktree_id)

        # Audit log (structured, grep-able). Reserved keyword ``audit`` makes
        # ``grep 'audit=force_unregister'`` a reliable supervisor query even
        # if wording around it changes later.
        logger.info(
            "audit=force_unregister worktree_id=%s caller_project_id=%s already_unregistered=%s",
            worktree_id,
            caller_project_id if caller_project_id else "mcp_service",
            already_unregistered,
        )

        return {
            "worktree_id": worktree_id,
            "already_unregistered": already_unregistered,
        }

    async def unregister_by_path(
        self,
        project_id: UUID,
        worktree_path: str,
        artifacts: dict[str, str | None] | None = None,
    ) -> None:
        """Resolve worktree by path and unregister it."""
        worktree = await self._repo.get_worktree_by_path(project_id, worktree_path)
        if worktree is None:
            raise ValueError(f"Worktree not found for path: {worktree_path}")
        await self.unregister(worktree.id, artifacts=artifacts)

    async def remove_offline_agents(self, project_id: UUID) -> int:
        """Delete all offline worktree records for a project. Returns count removed."""
        offline = await self._repo.get_offline_worktrees(project_id)
        for wt in offline:
            # End any lingering sessions
            session = await self._repo.get_active_session(wt.id)
            if session is not None:
                await self._repo.end_session(session.id)
            await self._repo.delete_worktree(wt.id)
        return len(offline)

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
                event_data = {
                    "worktree_id": str(session.worktree_id),
                    "reason": "heartbeat_timeout",
                }
                await event_bus.publish(
                    Event(
                        type=EventType.WORKTREE_OFFLINE,
                        project_id=worktree.project_id,
                        data=event_data,
                    )
                )
                # T-358: heartbeat timeout is a non-clean exit -- the agent
                # process is gone without calling unregister_agent. Surface it
                # to the desktop-toast dispatcher.
                await event_bus.publish(
                    Event(
                        type=EventType.AGENT_UNREGISTERED,
                        project_id=worktree.project_id,
                        data=event_data,
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
