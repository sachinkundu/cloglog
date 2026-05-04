"""Pydantic schemas for the Board context API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.shared.text import NulSanitizedModel

_NulSanitized = NulSanitizedModel  # local alias for readability

# --- Project ---


class ProjectCreate(_NulSanitized):
    name: str
    description: str = ""
    repo_url: str = ""


class ProjectUpdate(_NulSanitized):
    # ``Project.name`` and ``Project.description`` are NOT NULL columns
    # with a default of ``""``. Typing them as plain ``str`` (not
    # ``str | None``) makes Pydantic 422 on explicit JSON ``null`` —
    # matching the reality of the column AND keeping the generated
    # OpenAPI's ``name?: string`` / ``description?: string`` shape
    # consistent with the contract clients consume (codex review on
    # PR #270 round 4). ``model_dump(exclude_unset=True)`` still excludes
    # fields the caller didn't send, so the omit-to-leave-unchanged
    # PATCH semantics are preserved.
    #
    # ``repo_url`` stays ``str | None`` because explicit ``null`` is the
    # documented "clear" value (the service coerces it to ``""`` for
    # the NOT NULL column).
    name: str = ""
    description: str = ""
    repo_url: str | None = None


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


class EpicCreate(_NulSanitized):
    title: str
    description: str = ""
    bounded_context: str = ""
    context_description: str = ""
    position: int = 0


class EpicUpdate(_NulSanitized):
    title: str | None = None
    description: str | None = None
    bounded_context: str | None = None
    context_description: str | None = None
    status: str | None = None


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


class FeatureCreate(_NulSanitized):
    title: str
    description: str = ""
    position: int = 0


class FeatureUpdate(_NulSanitized):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    position: int | None = None


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


VALID_TASK_TYPES = {"spec", "plan", "impl", "task"}
PIPELINE_ORDER = {"spec": 0, "plan": 1, "impl": 2, "task": -1}


class TaskCreate(_NulSanitized):
    title: str
    description: str = ""
    priority: str = "normal"
    position: int = 0
    task_type: str = "task"
    model: str | None = None


class TaskUpdate(_NulSanitized):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    worktree_id: UUID | None = None
    position: int | None = None
    archived: bool | None = None
    retired: bool | None = None
    pr_url: str | None = None
    pr_merged: bool | None = None
    model: str | None = None


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    feature_id: UUID
    title: str
    description: str
    status: str
    priority: str
    task_type: str
    model: str | None = None
    pr_url: str | None
    pr_merged: bool
    artifact_path: str | None = None
    worktree_id: UUID | None
    position: int
    number: int
    archived: bool
    retired: bool
    created_at: datetime
    updated_at: datetime


# --- Close-off tasks ---


class CloseOffTaskCreate(_NulSanitized):
    worktree_path: str
    worktree_name: str


class CloseOffTaskResponse(BaseModel):
    task_id: UUID
    task_number: int
    worktree_id: UUID
    worktree_name: str
    created: bool  # False when an existing close-off task was returned (idempotent hit)


# --- Board view ---


class TaskCard(TaskResponse):
    """Task with breadcrumb info for the Kanban board."""

    epic_title: str = ""
    feature_title: str = ""
    epic_color: str = ""
    codex_review_picked_up: bool = False


class BoardColumn(BaseModel):
    status: str
    tasks: list[TaskCard]


class BoardResponse(BaseModel):
    project_id: UUID
    project_name: str
    columns: list[BoardColumn]
    total_tasks: int
    done_count: int


class ActiveTaskItem(BaseModel):
    """Compact task representation for the active-tasks endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: int
    title: str
    status: str
    pr_url: str | None
    pr_merged: bool
    worktree_id: UUID | None
    feature_id: UUID
    task_type: str
    model: str | None = None


# --- Backlog tree view ---


class BacklogTask(BaseModel):
    id: UUID
    number: int
    title: str
    status: str
    priority: str
    task_type: str = "task"
    pr_url: str | None = None
    pr_merged: bool = False
    artifact_path: str | None = None


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


# --- Search ---


class SearchResult(BaseModel):
    id: UUID
    type: str  # "epic" | "feature" | "task"
    title: str
    number: int
    status: str
    epic_title: str | None = None
    epic_color: str | None = None
    feature_title: str | None = None
    model: str | None = None  # populated for tasks only


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total: int


# --- Import ---


class ImportTask(_NulSanitized):
    title: str
    description: str = ""
    priority: str = "normal"


class ImportFeature(_NulSanitized):
    title: str
    description: str = ""
    tasks: list[ImportTask] = []


class ImportEpic(_NulSanitized):
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


# --- Reorder ---


class ReorderItem(BaseModel):
    id: UUID
    position: int


class ReorderRequest(BaseModel):
    items: list[ReorderItem]
