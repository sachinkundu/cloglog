"""Business logic for the Agent bounded context."""

from __future__ import annotations

import hashlib
import logging
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.agent.repository import AgentRepository
from src.board.models import Task
from src.board.repository import BoardRepository
from src.shared.config import settings
from src.shared.events import Event, EventType, event_bus

logger = logging.getLogger(__name__)


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
            "project_id": project_id,
            "current_task": current_task,
            "resumed": not is_new,
            "agent_token": agent_token,
        }

    # --- Shutdown ---

    async def request_shutdown(self, worktree_id: UUID) -> None:
        """Request agent shutdown via inbox file for instant Monitor delivery."""
        import json
        from pathlib import Path

        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        # Write shutdown message to inbox file — Monitor picks this up instantly
        inbox_path = Path(f"/tmp/cloglog-inbox-{worktree_id}")
        message = json.dumps(
            {
                "type": "shutdown",
                "message": (
                    "SHUTDOWN REQUESTED: The master agent has requested this worktree "
                    "to shut down. Finish your current work, generate shutdown artifacts "
                    "(work-log.md and learnings.md in shutdown-artifacts/), call "
                    "unregister_agent, and exit."
                ),
            }
        )
        inbox_path.write_text(message + "\n")

        # Also set the DB flag as fallback for agents not yet using Monitor
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

    def _check_pipeline_predecessors(self, task: Task, feature_tasks: list[Task]) -> None:
        """Check that predecessor task types in the pipeline are done."""
        if task.task_type == "task":
            return  # Standalone tasks have no pipeline deps

        predecessor_type: str | None = None
        if task.task_type == "plan":
            predecessor_type = "spec"
        elif task.task_type == "impl":
            predecessor_type = "plan"

        if predecessor_type is None:
            return

        predecessors = [t for t in feature_tasks if t.task_type == predecessor_type]
        if not predecessors:
            return  # No predecessor tasks exist — allow start

        # Accept "done" or "review with a pr_url" as completed — agents shouldn't
        # be blocked waiting for the user to drag a card to done on the board
        # when the PR is already merged.
        def is_completed(t: Task) -> bool:
            if t.status == "done":
                return True  # Human override — bypass artifact check
            if t.status == "review" and bool(t.pr_url):
                # For spec/plan predecessors, also require artifact attachment
                return not (t.task_type in ("spec", "plan") and not t.artifact_path)
            return False

        undone = [t for t in predecessors if not is_completed(t)]
        if undone:
            missing_artifact = [
                t for t in undone if t.status == "review" and bool(t.pr_url) and not t.artifact_path
            ]
            if missing_artifact:
                titles = ", ".join(f"T-{t.number}" for t in missing_artifact)
                raise ValueError(
                    f"Cannot start {task.task_type} task: "
                    f"{predecessor_type} task(s) {titles} in review but "
                    f"artifact not attached. "
                    f"Call report_artifact first."
                )
            titles = ", ".join(f"T-{t.number} ({t.status})" for t in undone)
            raise ValueError(
                f"Cannot start {task.task_type} task: "
                f"{predecessor_type} task(s) not done yet: "
                f"{titles}. "
                f"Wait for the {predecessor_type} PR to be merged."
            )

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
            if t.id != task_id
            and t.status in ("in_progress", "review")
            and not (t.status == "review" and t.pr_merged)
        ]
        if active:
            titles = ", ".join(f"T-{t.number} '{t.title}' ({t.status})" for t in active)
            raise ValueError(
                f"Cannot start task: agent already has active task(s): {titles}. "
                f"Finish or move the current task before starting a new one."
            )

        # Guard: check pipeline ordering (spec before plan, plan before impl)
        feature_tasks = await self._board_repo.get_tasks_for_feature(task.feature_id)
        self._check_pipeline_predecessors(task, feature_tasks)

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
                    "title": t.title,
                    "description": t.description,
                    "status": t.status,
                    "priority": t.priority,
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
        # Guard: agents cannot move tasks to done — only user can via board UI
        if status == "done":
            raise ValueError(
                "Agents cannot mark tasks as done. "
                "Move the task to 'review' and wait for the user "
                "to drag it to done on the board."
            )

        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        task = await self._board_repo.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

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

    async def mark_pr_merged(self, pr_url: str) -> dict[str, object]:
        """Set pr_merged=True on the task matching this PR URL.

        Called by agents when the polling loop detects a merge, as a fallback
        when the GitHub webhook hasn't fired (or isn't configured).
        """
        task = await self._board_repo.find_task_by_pr_url(pr_url)
        if task is None:
            raise ValueError(
                f"No active task found with pr_url={pr_url!r}. "
                "The task may already be done, or pr_url was never set."
            )
        await self._board_repo.update_task(task.id, pr_merged=True)
        logger.info("Marked task %s pr_merged=True via polling (pr_url=%s)", task.id, pr_url)
        return {"task_id": str(task.id), "pr_merged": True}

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
        """End the active session and delete worktree record."""
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

        await self._repo.delete_worktree(worktree_id)

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
