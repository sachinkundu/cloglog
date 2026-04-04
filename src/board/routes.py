"""FastAPI routes for the Board bounded context."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.repository import BoardRepository
from src.board.schemas import (
    BoardColumn,
    BoardResponse,
    EpicCreate,
    EpicResponse,
    FeatureCreate,
    FeatureResponse,
    ImportPlan,
    ProjectCreate,
    ProjectResponse,
    ProjectWithKey,
    TaskCard,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
)
from src.board.services import EPIC_COLOR_PALETTE, BoardService
from src.shared.database import get_session

router = APIRouter()

BOARD_COLUMNS = ["backlog", "assigned", "in_progress", "review", "done", "blocked"]


def _get_service(session: Annotated[AsyncSession, Depends(get_session)]) -> BoardService:
    return BoardService(BoardRepository(session))


ServiceDep = Annotated[BoardService, Depends(_get_service)]


# --- Projects ---


@router.post("/projects", response_model=ProjectWithKey, status_code=201)
async def create_project(body: ProjectCreate, service: ServiceDep) -> dict[str, object]:
    project, api_key = await service.create_project(body.name, body.description, body.repo_url)
    return {
        **ProjectResponse.model_validate(project).model_dump(),
        "api_key": api_key,
    }


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(service: ServiceDep) -> list[ProjectResponse]:
    projects = await service._repo.list_projects()
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: UUID, service: ServiceDep) -> ProjectResponse:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)


# --- Epics ---


@router.post(
    "/projects/{project_id}/epics",
    response_model=EpicResponse,
    status_code=201,
)
async def create_epic(project_id: UUID, body: EpicCreate, service: ServiceDep) -> EpicResponse:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    existing_count = await service._repo.count_epics(project_id)
    color = EPIC_COLOR_PALETTE[existing_count % len(EPIC_COLOR_PALETTE)]
    epic = await service._repo.create_epic(
        project_id,
        body.title,
        body.description,
        body.bounded_context,
        body.context_description,
        body.position,
        color=color,
    )
    return EpicResponse.model_validate(epic)


@router.get("/projects/{project_id}/epics", response_model=list[EpicResponse])
async def list_epics(project_id: UUID, service: ServiceDep) -> list[EpicResponse]:
    epics = await service._repo.list_epics(project_id)
    return [EpicResponse.model_validate(e) for e in epics]


# --- Features ---


@router.post(
    "/projects/{project_id}/epics/{epic_id}/features",
    response_model=FeatureResponse,
    status_code=201,
)
async def create_feature(
    project_id: UUID, epic_id: UUID, body: FeatureCreate, service: ServiceDep
) -> FeatureResponse:
    epic = await service._repo.get_epic(epic_id)
    if epic is None:
        raise HTTPException(status_code=404, detail="Epic not found")
    feature = await service._repo.create_feature(
        epic_id, body.title, body.description, body.position
    )
    return FeatureResponse.model_validate(feature)


@router.get(
    "/projects/{project_id}/epics/{epic_id}/features",
    response_model=list[FeatureResponse],
)
async def list_features(
    project_id: UUID, epic_id: UUID, service: ServiceDep
) -> list[FeatureResponse]:
    features = await service._repo.list_features(epic_id)
    return [FeatureResponse.model_validate(f) for f in features]


# --- Tasks ---


@router.post(
    "/projects/{project_id}/features/{feature_id}/tasks",
    response_model=TaskResponse,
    status_code=201,
)
async def create_task(
    project_id: UUID, feature_id: UUID, body: TaskCreate, service: ServiceDep
) -> TaskResponse:
    feature = await service._repo.get_feature(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    task = await service._repo.create_task(
        feature_id, body.title, body.description, body.priority, body.position
    )
    return TaskResponse.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(task_id: UUID, body: TaskUpdate, service: ServiceDep) -> TaskResponse:
    fields = body.model_dump(exclude_unset=True)
    task = await service._repo.update_task(task_id, **fields)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    # Trigger roll-up if status changed
    if "status" in fields:
        await service.recompute_rollup(task.feature_id)
    return TaskResponse.model_validate(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: UUID, service: ServiceDep) -> None:
    deleted = await service._repo.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")


# --- Board ---


@router.get("/projects/{project_id}/board", response_model=BoardResponse)
async def get_board(project_id: UUID, service: ServiceDep) -> BoardResponse:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    tasks = await service._repo.get_board_tasks(project_id)

    columns: dict[str, list[TaskCard]] = {col: [] for col in BOARD_COLUMNS}
    done_count = 0

    for task in tasks:
        card = TaskCard(
            **TaskResponse.model_validate(task).model_dump(),
            epic_title=task.feature.epic.title,
            feature_title=task.feature.title,
        )
        if task.status in columns:
            columns[task.status].append(card)
        if task.status == "done":
            done_count += 1

    return BoardResponse(
        project_id=project.id,
        project_name=project.name,
        columns=[BoardColumn(status=s, tasks=t) for s, t in columns.items()],
        total_tasks=len(tasks),
        done_count=done_count,
    )


# --- Import ---


@router.post("/projects/{project_id}/import", status_code=201)
async def import_plan(project_id: UUID, body: ImportPlan, service: ServiceDep) -> dict[str, int]:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return await service.import_plan(project_id, body)
