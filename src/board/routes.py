"""FastAPI routes for the Board bounded context."""

from __future__ import annotations

import contextlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.repository import AgentRepository
from src.agent.services import AgentService
from src.board.repository import BoardRepository
from src.board.schemas import (
    ActiveTaskItem,
    BacklogEpic,
    BacklogFeature,
    BacklogTask,
    BoardColumn,
    BoardResponse,
    DependencyCreate,
    DependencyGraphResponse,
    EpicCreate,
    EpicResponse,
    EpicUpdate,
    FeatureCreate,
    FeatureResponse,
    FeatureUpdate,
    ImportPlan,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    ProjectWithKey,
    ReorderRequest,
    SearchResponse,
    TaskCard,
    TaskCounts,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
)
from src.board.services import EPIC_COLOR_PALETTE, BoardService
from src.gateway.auth import CurrentMcpOrDashboard
from src.shared.database import get_session
from src.shared.events import Event, EventType, event_bus

router = APIRouter()

BOARD_COLUMNS = ["backlog", "prioritized", "in_progress", "review", "done"]


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


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID, body: ProjectUpdate, service: ServiceDep
) -> ProjectResponse:
    fields = body.model_dump(exclude_unset=True)
    project = await service.update_project(project_id, fields)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: UUID,
    service: ServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found") from None

    # Gracefully unregister all agents: ends sessions, publishes
    # WORKTREE_OFFLINE events, and deletes worktree records.
    agent_service = AgentService(AgentRepository(session), BoardRepository(session))
    worktrees = await agent_service._repo.get_worktrees_for_project(project_id)
    for wt in worktrees:
        with contextlib.suppress(ValueError):
            await agent_service.unregister(wt.id)

    deleted = await service._repo.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found") from None


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
    number = await service._repo.next_epic_number(project_id)
    epic = await service._repo.create_epic(
        project_id,
        body.title,
        body.description,
        body.bounded_context,
        body.context_description,
        body.position,
        color=color,
        number=number,
    )
    await event_bus.publish(
        Event(
            type=EventType.EPIC_CREATED,
            project_id=project_id,
            data={"epic_id": str(epic.id), "title": body.title},
        )
    )
    return EpicResponse.model_validate(epic)


@router.get("/projects/{project_id}/epics", response_model=list[EpicResponse])
async def list_epics(project_id: UUID, service: ServiceDep) -> list[EpicResponse]:
    epics = await service._repo.list_epics(project_id)
    return [EpicResponse.model_validate(e) for e in epics]


@router.patch("/epics/{epic_id}", response_model=EpicResponse)
async def update_epic(epic_id: UUID, body: EpicUpdate, service: ServiceDep) -> EpicResponse:
    fields = body.model_dump(exclude_unset=True)
    epic = await service._repo.update_epic(epic_id, **fields)
    if epic is None:
        raise HTTPException(status_code=404, detail="Epic not found")
    await event_bus.publish(
        Event(
            type=EventType.EPIC_CREATED,  # reuse for updates
            project_id=epic.project_id,
            data={"epic_id": str(epic_id), "title": epic.title},
        )
    )
    return EpicResponse.model_validate(epic)


@router.delete("/epics/{epic_id}", status_code=204)
async def delete_epic(epic_id: UUID, service: ServiceDep) -> None:
    epic = await service._repo.get_epic(epic_id)
    if epic is None:
        raise HTTPException(status_code=404, detail="Epic not found")
    project_id = epic.project_id
    deleted = await service._repo.delete_epic(epic_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Epic not found")
    await event_bus.publish(
        Event(
            type=EventType.EPIC_DELETED,
            project_id=project_id,
            data={"epic_id": str(epic_id)},
        )
    )


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
    number = await service._repo.next_feature_number(project_id)
    feature = await service._repo.create_feature(
        epic_id, body.title, body.description, body.position, number=number
    )
    await event_bus.publish(
        Event(
            type=EventType.FEATURE_CREATED,
            project_id=epic.project_id,
            data={"feature_id": str(feature.id), "title": body.title},
        )
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


@router.patch("/features/{feature_id}", response_model=FeatureResponse)
async def update_feature(
    feature_id: UUID, body: FeatureUpdate, service: ServiceDep
) -> FeatureResponse:
    fields = body.model_dump(exclude_unset=True)
    feature = await service._repo.update_feature(feature_id, **fields)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    await event_bus.publish(
        Event(
            type=EventType.FEATURE_CREATED,  # reuse for updates
            project_id=epic.project_id,
            data={"feature_id": str(feature_id), "title": feature.title},
        )
    )
    return FeatureResponse.model_validate(feature)


@router.delete("/features/{feature_id}", status_code=204)
async def delete_feature(feature_id: UUID, service: ServiceDep) -> None:
    feature = await service._repo.get_feature(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    project_id = epic.project_id
    deleted = await service._repo.delete_feature(feature_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Feature not found")
    await event_bus.publish(
        Event(
            type=EventType.FEATURE_DELETED,
            project_id=project_id,
            data={"feature_id": str(feature_id)},
        )
    )


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
    number = await service._repo.next_task_number(project_id)
    task = await service._repo.create_task(
        feature_id,
        body.title,
        body.description,
        body.priority,
        body.position,
        number=number,
        task_type=body.task_type,
        model=body.model,
    )
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    await event_bus.publish(
        Event(
            type=EventType.TASK_CREATED,
            project_id=epic.project_id,
            data={"task_id": str(task.id), "title": body.title},
        )
    )
    return TaskResponse.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(task_id: UUID, body: TaskUpdate, service: ServiceDep) -> TaskResponse:
    fields = body.model_dump(exclude_unset=True)
    # Capture old status before update for event emission
    old_status: str | None = None
    if "status" in fields:
        existing = await service._repo.get_task(task_id)
        if existing is not None:
            old_status = existing.status
            # Auto-assign position at end when moving to prioritized
            if fields["status"] == "prioritized" and old_status != "prioritized":
                max_pos = await service._repo.get_max_task_position(
                    existing.feature_id, "prioritized"
                )
                fields["position"] = max_pos + 1
    task = await service._repo.update_task(task_id, **fields)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    # Trigger roll-up if status changed
    if "status" in fields:
        await service.recompute_rollup(task.feature_id)
        # Emit event for SSE fan-out
        feature = await service._repo.get_feature(task.feature_id)
        assert feature is not None
        epic = await service._repo.get_epic(feature.epic_id)
        assert epic is not None
        await event_bus.publish(
            Event(
                type=EventType.TASK_STATUS_CHANGED,
                project_id=epic.project_id,
                data={
                    "task_id": str(task.id),
                    "old_status": old_status,
                    "new_status": fields["status"],
                },
            )
        )
        # Auto-attach document when spec/plan tasks move to review
        effective_pr_url = fields.get("pr_url") or task.pr_url
        if fields["status"] == "review" and effective_pr_url:
            doc = await service.auto_attach_document_on_review(task, str(effective_pr_url))
            if doc is not None:
                await event_bus.publish(
                    Event(
                        type=EventType.DOCUMENT_ATTACHED,
                        project_id=epic.project_id,
                        data={
                            "document_id": str(doc.id),
                            "attached_to_type": "feature",
                            "attached_to_id": str(task.feature_id),
                        },
                    )
                )
    return TaskResponse.model_validate(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: UUID, service: ServiceDep) -> None:
    task = await service._repo.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    feature = await service._repo.get_feature(task.feature_id)
    assert feature is not None
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    project_id = epic.project_id
    deleted = await service._repo.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    await event_bus.publish(
        Event(
            type=EventType.TASK_DELETED,
            project_id=project_id,
            data={"task_id": str(task_id)},
        )
    )


@router.post("/tasks/{task_id}/retire", response_model=TaskResponse)
async def retire_task(task_id: UUID, service: ServiceDep) -> TaskResponse:
    """Permanently retire a task — removes it from board and backlog views."""
    task = await service._repo.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found") from None
    if task.status != "done":
        raise HTTPException(status_code=400, detail="Only done tasks can be retired") from None
    task = await service._repo.update_task(task_id, retired=True)
    assert task is not None
    feature = await service._repo.get_feature(task.feature_id)
    assert feature is not None
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    await event_bus.publish(
        Event(
            type=EventType.TASK_RETIRED,
            project_id=epic.project_id,
            data={"task_id": str(task.id)},
        )
    )
    return TaskResponse.model_validate(task)


@router.post(
    "/projects/{project_id}/retire-done",
    status_code=200,
)
async def retire_all_done(project_id: UUID, service: ServiceDep) -> dict[str, int]:
    """Retire all archived done tasks for a project in bulk."""
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found") from None
    count = await service.retire_all_done(project_id)
    if count > 0:
        await event_bus.publish(
            Event(
                type=EventType.BULK_RETIRED,
                project_id=project_id,
                data={"retired_count": count},
            )
        )
    return {"retired_count": count}


@router.get("/tasks/{task_id}/notes")
async def get_task_notes(task_id: UUID, service: ServiceDep) -> list[dict[str, object]]:
    notes = await service._repo.get_task_notes(task_id)
    return [
        {"id": n.id, "task_id": n.task_id, "note": n.note, "created_at": n.created_at}
        for n in notes
    ]


# --- Notifications ---


@router.get("/projects/{project_id}/notifications")
async def get_notifications(project_id: UUID, service: ServiceDep) -> list[dict[str, object]]:
    notifications = await service._repo.get_unread_notifications(project_id)
    return [
        {
            "id": n.id,
            "project_id": n.project_id,
            "task_id": n.task_id,
            "task_title": n.task_title,
            "task_number": n.task_number,
            "read": n.read,
            "created_at": n.created_at,
        }
        for n in notifications
    ]


@router.patch("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: UUID, service: ServiceDep) -> dict[str, object]:
    notif = await service._repo.mark_notification_read(notification_id)
    if notif is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {
        "id": notif.id,
        "project_id": notif.project_id,
        "task_id": notif.task_id,
        "task_title": notif.task_title,
        "task_number": notif.task_number,
        "read": notif.read,
        "created_at": notif.created_at,
    }


@router.post("/projects/{project_id}/notifications/read-all")
async def mark_all_notifications_read(project_id: UUID, service: ServiceDep) -> dict[str, int]:
    count = await service._repo.mark_all_notifications_read(project_id)
    return {"marked_read": count}


@router.post(
    "/projects/{project_id}/notifications/dismiss-task/{task_id}",
    status_code=200,
)
async def dismiss_task_notification(
    project_id: UUID, task_id: UUID, service: ServiceDep
) -> dict[str, bool]:
    notif = await service._repo.get_unread_notification_for_task(project_id, task_id)
    if notif is not None:
        await service._repo.mark_notification_read(notif.id)
        return {"dismissed": True}
    return {"dismissed": False}


# --- Search ---


@router.get("/projects/{project_id}/search", response_model=SearchResponse)
async def search_project(
    project_id: UUID,
    service: ServiceDep,
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    status_filter: Annotated[list[str] | None, Query()] = None,
) -> SearchResponse:
    try:
        return await service.search(project_id, q, limit, status_filter=status_filter)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found") from None


# --- Reorder ---


@router.post("/projects/{project_id}/epics/reorder")
async def reorder_epics(
    project_id: UUID, body: ReorderRequest, service: ServiceDep
) -> dict[str, str]:
    try:
        positions = [(item.id, item.position) for item in body.items]
        await service._repo.reorder_epics(project_id, positions)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    await event_bus.publish(
        Event(
            type=EventType.EPIC_REORDERED,
            project_id=project_id,
            data={"project_id": str(project_id)},
        )
    )
    return {"status": "ok"}


@router.post("/projects/{project_id}/epics/{epic_id}/features/reorder")
async def reorder_features(
    project_id: UUID, epic_id: UUID, body: ReorderRequest, service: ServiceDep
) -> dict[str, str]:
    try:
        positions = [(item.id, item.position) for item in body.items]
        await service._repo.reorder_features(epic_id, positions)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    await event_bus.publish(
        Event(
            type=EventType.FEATURE_REORDERED,
            project_id=project_id,
            data={"epic_id": str(epic_id)},
        )
    )
    return {"status": "ok"}


@router.post("/features/{feature_id}/tasks/reorder")
async def reorder_tasks(
    feature_id: UUID, body: ReorderRequest, service: ServiceDep
) -> dict[str, str]:
    feature = await service._repo.get_feature(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    project_id = epic.project_id
    try:
        positions = [(item.id, item.position) for item in body.items]
        await service._repo.reorder_tasks(feature_id, positions)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    await event_bus.publish(
        Event(
            type=EventType.TASK_REORDERED,
            project_id=project_id,
            data={"feature_id": str(feature_id)},
        )
    )
    return {"status": "ok"}


# --- Board ---


@router.get("/projects/{project_id}/board", response_model=BoardResponse)
async def get_board(
    project_id: UUID,
    service: ServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: Annotated[list[str] | None, Query()] = None,
    epic_id: UUID | None = None,
    exclude_done: bool = False,
) -> BoardResponse:
    # DDD: Board projects a single boolean (``codex_review_picked_up``) from
    # the Review context via its Open Host Service factory. Board never
    # imports ``src.review.models`` or ``src.review.repository`` — only
    # ``src.review.services.make_review_turn_registry``, whose return type
    # is the ``IReviewTurnRegistry`` Protocol. See docs/ddd-context-map.md
    # and the pin test in tests/board/test_board_review_boundary.py.
    from src.review.services import make_review_turn_registry

    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Self-healing: assign colors to epics created before the color feature
    await service._repo.backfill_epic_colors(project_id, EPIC_COLOR_PALETTE)

    tasks = await service._repo.get_board_tasks(
        project_id, statuses=status, epic_id=epic_id, exclude_done=exclude_done
    )

    # Single batched query across all pr_urls on the board (T-260). One
    # round-trip per board load, not one per card. Empty input → empty set
    # short-circuits in the repository. ``project_id`` is passed through
    # so two cloglog projects tracking the same GitHub repo/PR URL never
    # leak codex badges across each other's boards — pr_url uniqueness
    # is feature-scoped today (see xfailed
    # ``test_pr_url_reuse_blocked_cross_feature``), so cross-project
    # collision is a real concern. PR #198 round 1 codex MEDIUM fix.
    pr_urls = [t.pr_url for t in tasks if t.pr_url]
    review_registry = make_review_turn_registry(session)
    codex_touched = await review_registry.codex_touched_pr_urls(
        project_id=project_id, pr_urls=pr_urls
    )

    columns: dict[str, list[TaskCard]] = {col: [] for col in BOARD_COLUMNS}
    done_count = 0

    for task in tasks:
        card = TaskCard(
            **TaskResponse.model_validate(task).model_dump(),
            epic_title=task.feature.epic.title,
            feature_title=task.feature.title,
            epic_color=task.feature.epic.color,
            codex_review_picked_up=bool(task.pr_url and task.pr_url in codex_touched),
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


@router.get(
    "/projects/{project_id}/active-tasks",
    response_model=list[ActiveTaskItem],
)
async def get_active_tasks(project_id: UUID, service: ServiceDep) -> list[ActiveTaskItem]:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    tasks = await service._repo.get_active_tasks(project_id)
    return [ActiveTaskItem.model_validate(t) for t in tasks]


# --- Backlog ---


@router.get("/projects/{project_id}/backlog", response_model=list[BacklogEpic])
async def get_backlog(project_id: UUID, service: ServiceDep) -> list[BacklogEpic]:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Self-healing: assign colors to epics created before the color feature
    await service._repo.backfill_epic_colors(project_id, EPIC_COLOR_PALETTE)

    epics = await service._repo.get_backlog_tree(project_id)
    result = []

    for epic in epics:
        epic_total = 0
        epic_done = 0
        features = []

        for feature in sorted(epic.features, key=lambda f: f.position):
            tasks = sorted(feature.tasks, key=lambda t: t.position)
            feat_total = len(tasks)
            feat_done = sum(1 for t in tasks if t.status == "done")
            epic_total += feat_total
            epic_done += feat_done

            features.append(
                BacklogFeature(
                    feature=FeatureResponse.model_validate(feature),
                    tasks=[
                        BacklogTask(
                            id=t.id,
                            number=t.number,
                            title=t.title,
                            status=t.status,
                            priority=t.priority,
                            pr_merged=t.pr_merged,
                        )
                        for t in tasks
                    ],
                    task_counts=TaskCounts(total=feat_total, done=feat_done),
                )
            )

        result.append(
            BacklogEpic(
                epic=EpicResponse.model_validate(epic),
                features=features,
                task_counts=TaskCounts(total=epic_total, done=epic_done),
            )
        )

    return result


# --- Dependencies ---


@router.get(
    "/projects/{project_id}/dependency-graph",
    response_model=DependencyGraphResponse,
)
async def get_dependency_graph(project_id: UUID, service: ServiceDep) -> DependencyGraphResponse:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    graph = await service.get_dependency_graph(project_id)
    return DependencyGraphResponse.model_validate(graph)


@router.post("/features/{feature_id}/dependencies", status_code=201)
async def add_dependency(
    feature_id: UUID,
    body: DependencyCreate,
    service: ServiceDep,
    _: CurrentMcpOrDashboard,
) -> dict[str, str]:
    try:
        await service.add_dependency(feature_id, body.depends_on_id)
    except ValueError as e:
        msg = str(e)
        if "DUPLICATE" in msg:
            raise HTTPException(status_code=409, detail="Dependency already exists") from None
        raise HTTPException(status_code=400, detail=msg) from None
    # Resolve project_id for SSE event
    feature = await service._repo.get_feature(feature_id)
    assert feature is not None
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    await event_bus.publish(
        Event(
            type=EventType.DEPENDENCY_ADDED,
            project_id=epic.project_id,
            data={
                "scope": "feature",
                "feature_id": str(feature_id),
                "depends_on_id": str(body.depends_on_id),
            },
        )
    )
    return {"status": "created"}


@router.delete("/features/{feature_id}/dependencies/{depends_on_id}", status_code=204)
async def remove_dependency(
    feature_id: UUID,
    depends_on_id: UUID,
    service: ServiceDep,
    _: CurrentMcpOrDashboard,
) -> None:
    # Resolve project_id for SSE event before deletion
    feature = await service._repo.get_feature(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    removed = await service.remove_dependency(feature_id, depends_on_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Dependency not found")
    await event_bus.publish(
        Event(
            type=EventType.DEPENDENCY_REMOVED,
            project_id=epic.project_id,
            data={
                "scope": "feature",
                "feature_id": str(feature_id),
                "depends_on_id": str(depends_on_id),
            },
        )
    )


# --- Task Dependencies (F-11) ---


@router.post("/tasks/{task_id}/dependencies", status_code=201)
async def add_task_dependency(
    task_id: UUID,
    body: DependencyCreate,
    service: ServiceDep,
    _: CurrentMcpOrDashboard,
) -> dict[str, str]:
    try:
        await service.add_task_dependency(task_id, body.depends_on_id)
    except ValueError as e:
        msg = str(e)
        if "DUPLICATE" in msg:
            raise HTTPException(status_code=409, detail="Dependency already exists") from None
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg) from None
        raise HTTPException(status_code=400, detail=msg) from None
    task = await service._repo.get_task(task_id)
    assert task is not None
    feature = await service._repo.get_feature(task.feature_id)
    assert feature is not None
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    await event_bus.publish(
        Event(
            type=EventType.DEPENDENCY_ADDED,
            project_id=epic.project_id,
            data={
                "scope": "task",
                "task_id": str(task_id),
                "depends_on_id": str(body.depends_on_id),
            },
        )
    )
    return {"status": "created"}


@router.delete("/tasks/{task_id}/dependencies/{depends_on_id}", status_code=204)
async def remove_task_dependency(
    task_id: UUID,
    depends_on_id: UUID,
    service: ServiceDep,
    _: CurrentMcpOrDashboard,
) -> None:
    task = await service._repo.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    feature = await service._repo.get_feature(task.feature_id)
    assert feature is not None
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    removed = await service.remove_task_dependency(task_id, depends_on_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Dependency not found")
    await event_bus.publish(
        Event(
            type=EventType.DEPENDENCY_REMOVED,
            project_id=epic.project_id,
            data={
                "scope": "task",
                "task_id": str(task_id),
                "depends_on_id": str(depends_on_id),
            },
        )
    )


# --- Import ---


@router.post("/projects/{project_id}/import", status_code=201)
async def import_plan(project_id: UUID, body: ImportPlan, service: ServiceDep) -> dict[str, int]:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    result = await service.import_plan(project_id, body)
    await event_bus.publish(
        Event(
            type=EventType.BULK_IMPORT,
            project_id=project_id,
            data={
                "epics_created": result["epics_created"],
                "features_created": result["features_created"],
                "tasks_created": result["tasks_created"],
            },
        )
    )
    return result


# --- Worktree Management (Dashboard) ---


@router.post(
    "/projects/{project_id}/worktrees/{worktree_id}/request-shutdown",
    status_code=200,
)
async def request_worktree_shutdown(
    project_id: UUID,
    worktree_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, bool]:
    """Request a worktree agent to shut down. Dashboard-facing endpoint.

    Delegates to ``AgentService.request_shutdown`` so the shutdown JSON
    line lands in ``<worktree_path>/.cloglog/inbox`` for sub-second
    Monitor delivery. The DB ``shutdown_requested`` flag is still set by
    the service itself as a fallback. A 404 is returned if the worktree
    doesn't belong to the project in the URL; a 409 is returned if the
    worktree row is in an unroutable state (empty ``worktree_path`` — a
    legacy-row guard, since new registrations are blocked at the schema).
    """
    agent_repo = AgentRepository(session)
    worktree = await agent_repo.get_worktree(worktree_id)
    if worktree is None or worktree.project_id != project_id:
        raise HTTPException(status_code=404, detail="Worktree not found")

    service = AgentService(agent_repo, BoardRepository(session))
    try:
        await service.request_shutdown(worktree_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    return {"shutdown_requested": True}


@router.post(
    "/projects/{project_id}/worktrees/remove-offline",
    status_code=200,
)
async def remove_offline_agents(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, int]:
    """Remove all offline agent records for a project. Dashboard-facing endpoint."""
    agent_service = AgentService(AgentRepository(session), BoardRepository(session))
    count = await agent_service.remove_offline_agents(project_id)
    if count > 0:
        await event_bus.publish(
            Event(
                type=EventType.BULK_AGENTS_REMOVED,
                project_id=project_id,
                data={"removed_count": count},
            )
        )
    return {"removed_count": count}
