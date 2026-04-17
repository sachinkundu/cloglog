"""FastAPI routes for the Agent bounded context (agent-facing endpoints)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.repository import AgentRepository
from src.agent.schemas import (
    AddTaskNoteRequest,
    AssignTaskRequest,
    CompleteTaskRequest,
    CompleteTaskResponse,
    HeartbeatResponse,
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
from src.gateway.auth import CurrentAgent, CurrentProject, SupervisorAuth
from src.shared.database import get_session
from src.shared.events import Event, EventType, event_bus

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


@router.post("/agents/{worktree_id}/start-task", response_model=StartTaskResponse)
async def start_task(
    worktree_id: UUID, body: StartTaskRequest, service: ServiceDep, agent: CurrentAgent
) -> dict[str, object]:
    try:
        return await service.start_task(worktree_id, body.task_id)
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
async def request_shutdown(worktree_id: UUID, service: ServiceDep) -> dict[str, bool]:
    """Request a worktree agent to shut down gracefully.

    Writes a shutdown message to the agent's inbox file for instant
    Monitor-based delivery (sub-second latency), replacing the old
    heartbeat polling approach.
    """
    worktree = await service._repo.get_worktree(worktree_id)
    if worktree is None:
        raise HTTPException(status_code=404, detail="Worktree not found")
    await service.request_shutdown(worktree_id)
    return {"shutdown_requested": True}


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
async def list_worktrees(project_id: UUID, service: ServiceDep) -> list[dict[str, object]]:
    return await service.get_worktrees_for_project(project_id)
