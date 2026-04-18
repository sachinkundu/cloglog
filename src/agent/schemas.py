"""Pydantic schemas for the Agent context API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# --- Registration ---


class RegisterRequest(BaseModel):
    worktree_path: str
    branch_name: str = ""


class RegisterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    worktree_id: UUID
    session_id: UUID
    project_id: UUID
    current_task: TaskInfo | None = None
    resumed: bool = False
    agent_token: str | None = None


# --- Heartbeat ---


class HeartbeatResponse(BaseModel):
    status: str
    last_heartbeat: datetime


# --- Task lifecycle ---


class StartTaskRequest(BaseModel):
    task_id: UUID


class StartTaskResponse(BaseModel):
    task_id: UUID
    status: str


class CompleteTaskRequest(BaseModel):
    task_id: UUID
    pr_url: str | None = None


class CompleteTaskResponse(BaseModel):
    completed_task_id: UUID
    next_task: TaskInfo | None = None


class UpdateTaskStatusRequest(BaseModel):
    task_id: UUID
    status: str  # review, blocked, etc.
    pr_url: str | None = None
    skip_pr: bool = False  # Allow review without PR for docs/research tasks


class TaskInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str
    status: str
    priority: str
    artifact_path: str | None = None


class AssignTaskRequest(BaseModel):
    task_id: UUID


class AddTaskNoteRequest(BaseModel):
    task_id: UUID
    note: str


class MarkPrMergedRequest(BaseModel):
    pr_url: str


class ReportArtifactRequest(BaseModel):
    task_id: UUID
    artifact_path: str


class ArtifactPaths(BaseModel):
    work_log: str | None = None
    learnings: str | None = None


class UnregisterByPathRequest(BaseModel):
    worktree_path: str
    artifacts: ArtifactPaths | None = None


# --- Worktree ---


class WorktreeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    worktree_path: str
    branch_name: str
    status: str
    current_task_id: UUID | None
    last_heartbeat: datetime | None
    created_at: datetime


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    worktree_id: UUID
    started_at: datetime
    ended_at: datetime | None
    last_heartbeat: datetime
    status: str


# Fix forward reference
RegisterResponse.model_rebuild()
