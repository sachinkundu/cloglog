"""FastAPI routes for the Agent bounded context (agent-facing endpoints)."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.exceptions import TaskBlockedError
from src.agent.repository import AgentRepository
from src.agent.schemas import (
    AddTaskNoteRequest,
    AssignTaskRequest,
    CompleteTaskRequest,
    CompleteTaskResponse,
    ForceUnregisterResponse,
    HeartbeatResponse,
    MarkPrMergedRequest,
    RegisterRequest,
    RegisterResponse,
    ReportArtifactRequest,
    StartTaskRequest,
    StartTaskResponse,
    TaskInfo,
    UnregisterByPathRequest,
    UpdateTaskStatusRequest,
    WorktreeResponse,
)
from src.agent.services import AgentService
from src.board.repository import BoardRepository
from src.board.schemas import CloseOffTaskCreate, CloseOffTaskResponse
from src.board.services import BoardService
from src.gateway.auth import (
    CurrentAgent,
    CurrentMcpOrDashboard,
    CurrentProject,
    McpOrProject,
    SupervisorAuth,
)
from src.shared.config import settings
from src.shared.database import get_session
from src.shared.events import Event, EventType, event_bus

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_service(session: Annotated[AsyncSession, Depends(get_session)]) -> AgentService:
    return AgentService(AgentRepository(session), BoardRepository(session))


ServiceDep = Annotated[AgentService, Depends(_get_service)]


@router.post("/agents/register", response_model=RegisterResponse, status_code=201)
async def register_agent(
    body: RegisterRequest, service: ServiceDep, project: CurrentProject
) -> dict[str, object]:
    """Register a worktree agent. Requires valid API key."""
    result = await service.register(project.id, body.worktree_path, body.branch_name)
    return result


@router.post("/agents/{worktree_id}/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    worktree_id: UUID, service: ServiceDep, agent: CurrentAgent
) -> dict[str, object]:
    try:
        return await service.heartbeat(worktree_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/agents/{worktree_id}/tasks", response_model=list[TaskInfo])
async def get_tasks(worktree_id: UUID, service: ServiceDep, agent: CurrentAgent) -> list[TaskInfo]:
    """Get all tasks assigned to this worktree."""
    tasks = await service._board_repo.get_tasks_for_worktree(worktree_id)
    return [TaskInfo.model_validate(t) for t in tasks]


@router.patch("/agents/{worktree_id}/assign-task", status_code=200)
async def assign_task(
    worktree_id: UUID, body: AssignTaskRequest, service: ServiceDep, target: SupervisorAuth
) -> dict[str, object]:
    """Assign a task to a worktree without changing its status.

    Supervisor action: accepts MCP service key, the target project's API key,
    or the target agent's own token.
    """
    try:
        return await service.assign_task(worktree_id, body.task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


def _blocked_detail(err: TaskBlockedError) -> dict[str, object]:
    return {
        "code": err.code,
        "message": str(err),
        "blockers": err.blockers,
    }


@router.post("/agents/{worktree_id}/start-task", response_model=StartTaskResponse)
async def start_task(
    worktree_id: UUID, body: StartTaskRequest, service: ServiceDep, agent: CurrentAgent
) -> dict[str, object]:
    try:
        return await service.start_task(worktree_id, body.task_id)
    except TaskBlockedError as e:
        raise HTTPException(status_code=409, detail=_blocked_detail(e)) from None
    except ValueError as e:
        status = 409 if "Cannot start" in str(e) else 404
        raise HTTPException(status_code=status, detail=str(e)) from None


@router.post("/agents/{worktree_id}/complete-task", response_model=CompleteTaskResponse)
async def complete_task(
    worktree_id: UUID, body: CompleteTaskRequest, service: ServiceDep, agent: CurrentAgent
) -> dict[str, object]:
    try:
        return await service.complete_task(worktree_id, body.task_id, pr_url=body.pr_url)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.patch("/agents/{worktree_id}/task-status", status_code=204)
async def update_task_status(
    worktree_id: UUID, body: UpdateTaskStatusRequest, service: ServiceDep, agent: CurrentAgent
) -> None:
    try:
        await service.update_task_status(
            worktree_id, body.task_id, body.status, pr_url=body.pr_url, skip_pr=body.skip_pr
        )
    except TaskBlockedError as e:
        raise HTTPException(status_code=409, detail=_blocked_detail(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.post("/agents/{worktree_id}/task-note", status_code=201)
async def add_task_note(
    worktree_id: UUID, body: AddTaskNoteRequest, service: ServiceDep, agent: CurrentAgent
) -> dict[str, object]:
    task = await service._board_repo.get_task(body.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    note = await service._board_repo.add_task_note(body.task_id, body.note)
    feature = await service._board_repo.get_feature(task.feature_id)
    assert feature is not None
    epic = await service._board_repo.get_epic(feature.epic_id)
    assert epic is not None
    await event_bus.publish(
        Event(
            type=EventType.TASK_NOTE_ADDED,
            project_id=epic.project_id,
            data={"task_id": str(body.task_id)},
        )
    )
    return {
        "id": note.id,
        "task_id": note.task_id,
        "note": note.note,
        "created_at": note.created_at,
    }


@router.post("/agents/{worktree_id}/mark-pr-merged", status_code=200)
async def mark_pr_merged(
    worktree_id: UUID, body: MarkPrMergedRequest, service: ServiceDep, agent: CurrentAgent
) -> dict[str, object]:
    """Mark the task matching this PR URL as pr_merged=True.

    Called by agents when the polling loop detects a GitHub PR was merged,
    as a fallback when the GitHub webhook hasn't fired.
    """
    try:
        return await service.mark_pr_merged(worktree_id, body.task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.post("/agents/{worktree_id}/report-artifact", status_code=200)
async def report_artifact(
    worktree_id: UUID, body: ReportArtifactRequest, service: ServiceDep
) -> dict[str, object]:
    """Report the artifact path for a spec/plan task after its PR merges."""
    try:
        return await service.report_artifact(worktree_id, body.task_id, body.artifact_path)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.post("/agents/{worktree_id}/request-shutdown", status_code=200)
async def request_shutdown(
    worktree_id: UUID, service: ServiceDep, target: SupervisorAuth
) -> dict[str, bool]:
    """Request a worktree agent to shut down gracefully.

    Writes a shutdown JSON line to ``<worktree_path>/.cloglog/inbox`` for
    instant Monitor-based delivery. If the stored worktree_path is empty
    (legacy rows predating the schema's ``min_length=1``), the service
    raises ``ValueError`` and we translate that to a 409 rather than letting
    it bubble out as a 500.

    Auth (``SupervisorAuth``) — before T-218 this route had no per-route
    dependency and the gateway middleware passed any ``Authorization:
    Bearer ...`` header through on ``/api/v1/agents/*``. Exposing the
    endpoint as an MCP tool made that pre-existing hole reachable, so the
    route now validates credentials: MCP service key, project API key
    (project must own the target worktree), or the target agent's own
    token. Mirrors the assign-task bar for consistency.
    """
    try:
        await service.request_shutdown(worktree_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    return {"shutdown_requested": True}


@router.post(
    "/agents/{worktree_id}/force-unregister",
    response_model=ForceUnregisterResponse,
    status_code=200,
)
async def force_unregister(
    worktree_id: UUID, service: ServiceDep, caller: McpOrProject
) -> dict[str, object]:
    """Supervisor force-unregister — tier-2 fallback for a wedged worktree.

    Auth: MCP service key OR project API key. Agent tokens are refused so
    a wedged agent cannot force-unregister itself (which would defeat the
    purpose of the tier-2 fallback). Idempotent: returns
    ``{"already_unregistered": true}`` when the worktree row is already
    gone, without re-emitting ``WORKTREE_OFFLINE``.
    """
    caller_project_id = caller.id if caller is not None else None
    try:
        return await service.force_unregister(worktree_id, caller_project_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from None


@router.post("/agents/unregister-by-path", status_code=204)
async def unregister_by_path(
    body: UnregisterByPathRequest, service: ServiceDep, project: CurrentProject
) -> None:
    artifacts = None
    if body.artifacts is not None:
        artifacts = {
            "work_log": body.artifacts.work_log,
            "learnings": body.artifacts.learnings,
        }
    try:
        await service.unregister_by_path(project.id, body.worktree_path, artifacts=artifacts)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/agents/{worktree_id}/unregister", status_code=204)
async def unregister_agent(worktree_id: UUID, service: ServiceDep, agent: CurrentAgent) -> None:
    try:
        await service.unregister(worktree_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/projects/{project_id}/worktrees", response_model=list[WorktreeResponse])
async def list_worktrees(
    project_id: UUID,
    service: ServiceDep,
    _: CurrentMcpOrDashboard,
) -> list[dict[str, object]]:
    """List worktrees for a project.

    AUTH: NOT a public route. Two gates fire for every request:

    1. ``ApiAccessControlMiddleware`` (``src/gateway/app.py``) — checks
       that ONE of ``X-MCP-Request``, ``X-Dashboard-Key``, or
       ``Authorization: Bearer ...`` is present. This is a *presence*
       check only; it does NOT validate the token value.
    2. ``CurrentMcpOrDashboard`` (``src/gateway/auth.py``) — the
       per-route ``Depends`` on this handler. This is where the token
       value is actually validated. Required shapes:
       - ``X-MCP-Request: true`` + ``Authorization: Bearer <mcp_service_key>``
         (matched against ``settings.mcp_service_key``). An invalid
         bearer under this shape returns ``401 Invalid MCP service key``
         — before T-258/codex-round-2, the middleware passed it through
         and the handler ran without further validation.
       - ``X-Dashboard-Key: <DASHBOARD_SECRET>`` (matched against
         ``settings.dashboard_secret``). Invalid → ``403 Invalid
         dashboard key`` from the middleware.

    Status codes surfaced:
    - ``401 Authentication required`` — no credential at all.
    - ``401 Invalid MCP service key`` — X-MCP-Request present but
      bearer does not match (enforced here by the Depends).
    - ``401 Missing or invalid credentials`` — X-MCP-Request absent and
      no valid dashboard key (enforced here by the Depends).
    - ``403 Invalid dashboard key`` — dashboard key present but wrong
      (middleware rejects before Depends runs).
    - ``403 Agents can only access /api/v1/agents/* routes`` — bare
      agent token on this non-agent route (middleware rejects first).

    Do NOT add this route to the middleware allowlist — T-244 reviewers
    flagged the ambiguity precisely because callers were silently
    relying on env-passthrough of the dashboard key; Option B of T-258
    keeps the auth required and makes callers pass the header
    explicitly. See ``docs/ddd-context-map.md § Auth Contract`` and
    ``docs/design.md § Authentication Flow`` for the full
    route-to-credential mapping.
    """
    return await service.get_worktrees_for_project(project_id)


@router.post(
    "/agents/close-off-task",
    response_model=CloseOffTaskResponse,
    status_code=201,
)
async def create_close_off_task(
    body: CloseOffTaskCreate,
    service: ServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
    project: CurrentProject,
) -> CloseOffTaskResponse:
    """Find-or-create the paired close-off task for a worktree (T-246).

    Called by ``.cloglog/on-worktree-create.sh`` and the
    ``mcp__cloglog__create_close_off_task`` MCP tool so every new worktree
    lands a first-class teardown card on the board. Idempotent on the
    resolved worktree row: relaunching/resuming the same worktree path
    returns the existing task with ``created=false``. Assigns the task to
    the main-agent worktree (resolved via ``worktrees.role='main'``, T-245)
    when that mapping is available; otherwise the card stays unassigned and
    still surfaces to the supervisor on backlog.

    Sibling to ``register_agent`` / ``unregister-by-path`` — same caller
    (launch skill or worktree-bootstrap hook), same project-API-key auth,
    same path-keyed lookup semantics.
    """
    agent_repo = AgentRepository(session)
    worktree = await agent_repo.get_worktree_by_path(project.id, body.worktree_path)
    if worktree is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Worktree not registered for this project: {body.worktree_path}. "
                "Call register_agent first."
            ),
        ) from None

    # Resolve the main-agent worktree via the role column (T-245) so the
    # close-off task gets assigned to it. Falls back to the documented
    # ``settings.main_agent_inbox_path`` when no role='main' row exists yet —
    # operators may have configured the env var but not yet run
    # ``/cloglog setup`` (the manual step that registers the main agent).
    # When neither resolves, the card stays unassigned and still surfaces on
    # the supervisor's backlog.
    main_agent = await agent_repo.get_main_agent_worktree(project.id)
    if main_agent is None and settings.main_agent_inbox_path is not None:
        # The main-agent inbox lives at ``<main-clone>/.cloglog/inbox`` —
        # the parent directory's parent is the main agent's worktree_path.
        legacy_path = str(settings.main_agent_inbox_path.parent.parent)
        main_agent = await agent_repo.get_worktree_by_path(project.id, legacy_path)
    main_agent_worktree_id: UUID | None = main_agent.id if main_agent is not None else None

    board_service = BoardService(BoardRepository(session))
    task, created = await board_service.create_close_off_task(
        project_id=project.id,
        close_off_worktree_id=worktree.id,
        worktree_name=body.worktree_name,
        main_agent_worktree_id=main_agent_worktree_id,
    )

    # T-305: warn iff the persisted close-off task is unassigned. The
    # endpoint is idempotent (services.py find_close_off_task returns the
    # existing row before recomputing assignment), so a resume/retry where
    # the main agent was registered earlier but no longer resolves now
    # MUST NOT re-emit the diagnostic — the task is already assigned in
    # the DB. Gating on ``task.worktree_id`` (the persisted state), not
    # ``main_agent_worktree_id`` (this-call resolver state), is the only
    # way to keep the warning truthful across resume calls.
    if task.worktree_id is None:
        # Three distinct causes — only one is true at a time, so the
        # warning text must branch on resolver outcome FIRST. Codex round 2
        # caught this: a resume call after the operator runs /cloglog setup
        # resolves main_agent_worktree_id successfully, but the idempotent
        # service path returns the existing unassigned row without
        # backfilling, so blaming "no role='main' worktree" or "inbox_path
        # misrouted" sends the operator down the wrong remedy. Gate on
        # resolver outcome first; only fall through to env-var diagnostics
        # when resolution actually failed.
        if main_agent_worktree_id is not None:
            cause = (
                "main agent now resolves but the idempotent close-off-task "
                "service path did not backfill worktree_id on the existing "
                "row (created by an earlier call when no main agent was "
                "registered)"
            )
            remedy = (
                "Reassign the task to the main agent — e.g. "
                "mcp__cloglog__assign_task or a direct PATCH on the task."
            )
        elif settings.main_agent_inbox_path is None:
            cause = "no role='main' worktree and main_agent_inbox_path is unset"
            remedy = "Run /cloglog setup or backfill worktrees.role to fix."
        else:
            cause = (
                "no role='main' worktree; main_agent_inbox_path is configured "
                f"({settings.main_agent_inbox_path}) but does not point at a "
                "registered worktree"
            )
            remedy = (
                "Run /cloglog setup so the main agent registers, or correct "
                "MAIN_AGENT_INBOX_PATH to point at a registered worktree."
            )
        logger.warning(
            "Close-off task for worktree %s (%s) is unassigned: %s for project %s. %s",
            body.worktree_path,
            body.worktree_name,
            cause,
            project.id,
            remedy,
        )

    if created:
        await event_bus.publish(
            Event(
                type=EventType.TASK_CREATED,
                project_id=project.id,
                data={
                    "task_id": str(task.id),
                    "title": task.title,
                    "close_off_worktree_id": str(worktree.id),
                },
            )
        )

    return CloseOffTaskResponse(
        task_id=task.id,
        task_number=task.number,
        worktree_id=worktree.id,
        worktree_name=body.worktree_name,
        created=created,
    )
