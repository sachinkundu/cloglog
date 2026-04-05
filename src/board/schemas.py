"""Pydantic schemas for the Board context API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# --- Project ---


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    repo_url: str = ""


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    repo_url: str
    status: str
    created_at: datetime


class ProjectWithKey(ProjectResponse):
    api_key: str  # Only returned on creation (plaintext, shown once)


class ProjectSummary(ProjectResponse):
    """Project with aggregated stats for the sidebar."""

    epic_count: int = 0
    task_count: int = 0
    done_count: int = 0
    active_worktree_count: int = 0


# --- Epic ---


class EpicCreate(BaseModel):
    title: str
    description: str = ""
    bounded_context: str = ""
    context_description: str = ""
    position: int = 0


class EpicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    description: str
    bounded_context: str
    context_description: str
    status: str
    position: int
    color: str
    number: int
    created_at: datetime


# --- Feature ---


class FeatureCreate(BaseModel):
    title: str
    description: str = ""
    position: int = 0


class FeatureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    epic_id: UUID
    title: str
    description: str
    status: str
    position: int
    number: int
    created_at: datetime


# --- Task ---


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    priority: str = "normal"
    position: int = 0


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    worktree_id: UUID | None = None
    position: int | None = None
    archived: bool | None = None


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    feature_id: UUID
    title: str
    description: str
    status: str
    priority: str
    worktree_id: UUID | None
    position: int
    number: int
    archived: bool
    created_at: datetime
    updated_at: datetime


# --- Board view ---


class TaskCard(TaskResponse):
    """Task with breadcrumb info for the Kanban board."""

    epic_title: str = ""
    feature_title: str = ""
    epic_color: str = ""


class BoardColumn(BaseModel):
    status: str
    tasks: list[TaskCard]


class BoardResponse(BaseModel):
    project_id: UUID
    project_name: str
    columns: list[BoardColumn]
    total_tasks: int
    done_count: int


# --- Backlog tree view ---


class BacklogTask(BaseModel):
    id: UUID
    number: int
    title: str
    status: str
    priority: str


class TaskCounts(BaseModel):
    total: int
    done: int


class BacklogFeature(BaseModel):
    feature: FeatureResponse
    tasks: list[BacklogTask]
    task_counts: TaskCounts


class BacklogEpic(BaseModel):
    epic: EpicResponse
    features: list[BacklogFeature]
    task_counts: TaskCounts


# --- Import ---


class ImportTask(BaseModel):
    title: str
    description: str = ""
    priority: str = "normal"


class ImportFeature(BaseModel):
    title: str
    description: str = ""
    tasks: list[ImportTask] = []


class ImportEpic(BaseModel):
    title: str
    description: str = ""
    bounded_context: str = ""
    features: list[ImportFeature] = []


class ImportPlan(BaseModel):
    epics: list[ImportEpic]


# --- Dependencies ---


class DependencyCreate(BaseModel):
    depends_on_id: UUID


class DependencyGraphNode(BaseModel):
    id: UUID
    number: int
    title: str
    status: str
    epic_title: str
    epic_color: str


class DependencyGraphEdge(BaseModel):
    from_id: UUID
    to_id: UUID
    from_number: int
    to_number: int


class DependencyGraphResponse(BaseModel):
    nodes: list[DependencyGraphNode]
    edges: list[DependencyGraphEdge]
