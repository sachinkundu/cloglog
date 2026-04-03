# Phase 1: Board Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Board bounded context — Projects, Epics, Features, Tasks with CRUD, bulk import, status roll-up, and all dashboard-read + management API endpoints.

**Architecture:** Standard DDD layers — SQLAlchemy models, Pydantic schemas, repository (DB queries), services (business logic including roll-up), FastAPI routes. All files live in `src/board/` and `tests/board/`. The Board context owns 5 tables: projects, epics, features, feature_dependencies, tasks.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Pydantic v2, pytest, PostgreSQL

**Worktree:** `wt-board` — only touch `src/board/`, `tests/board/`, `src/alembic/`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/board/models.py` | SQLAlchemy models: Project, Epic, Feature, FeatureDependency, Task |
| `src/board/schemas.py` | Pydantic request/response schemas |
| `src/board/repository.py` | Async DB queries (CRUD, filtering, roll-up updates) |
| `src/board/services.py` | Business logic: API key generation, status roll-up, import parsing |
| `src/board/routes.py` | FastAPI router with all Board endpoints |
| `src/board/interfaces.py` | Already exists — TaskAssignmentService, TaskStatusService protocols |
| `tests/board/test_models.py` | Model creation and relationship tests |
| `tests/board/test_services.py` | Roll-up logic, import parsing, API key hashing |
| `tests/board/test_routes.py` | Integration tests for all endpoints |

---

### Task 1: SQLAlchemy Models

**Files:**
- Create: `src/board/models.py`
- Test: `tests/board/test_models.py`

- [ ] **Step 1: Write model creation tests**

```python
# tests/board/test_models.py
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Epic, Feature, FeatureDependency, Project, Task


async def test_create_project(db_session: AsyncSession):
    project = Project(name="test-project", description="A test project")
    db_session.add(project)
    await db_session.commit()

    result = await db_session.execute(select(Project).where(Project.name == "test-project"))
    row = result.scalar_one()
    assert row.name == "test-project"
    assert row.status == "active"
    assert row.id is not None


async def test_create_full_hierarchy(db_session: AsyncSession):
    project = Project(name="hierarchy-test")
    db_session.add(project)
    await db_session.flush()

    epic = Epic(project_id=project.id, title="Auth Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Login Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    task = Task(feature_id=feature.id, title="Add login form", position=0)
    db_session.add(task)
    await db_session.commit()

    result = await db_session.execute(
        select(Task).where(Task.title == "Add login form")
    )
    row = result.scalar_one()
    assert row.status == "backlog"
    assert row.feature_id == feature.id


async def test_feature_dependency(db_session: AsyncSession):
    project = Project(name="dep-test")
    db_session.add(project)
    await db_session.flush()

    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature_a = Feature(epic_id=epic.id, title="Feature A", position=0)
    feature_b = Feature(epic_id=epic.id, title="Feature B", position=1)
    db_session.add_all([feature_a, feature_b])
    await db_session.flush()

    dep = FeatureDependency(feature_id=feature_b.id, depends_on_id=feature_a.id)
    db_session.add(dep)
    await db_session.commit()

    result = await db_session.execute(
        select(FeatureDependency).where(FeatureDependency.feature_id == feature_b.id)
    )
    row = result.scalar_one()
    assert row.depends_on_id == feature_a.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-board`
Expected: ImportError — `src.board.models` does not exist yet.

- [ ] **Step 3: Implement models**

```python
# src/board/models.py
"""SQLAlchemy models for the Board bounded context."""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    repo_url: Mapped[str] = mapped_column(String(500), default="")
    api_key_hash: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    epics: Mapped[list[Epic]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Epic(Base):
    __tablename__ = "epics"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    bounded_context: Mapped[str] = mapped_column(String(100), default="")
    context_description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="planned")
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    project: Mapped[Project] = relationship(back_populates="epics")
    features: Mapped[list[Feature]] = relationship(
        back_populates="epic", cascade="all, delete-orphan"
    )


class Feature(Base):
    __tablename__ = "features"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    epic_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("epics.id"))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="planned")
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    epic: Mapped[Epic] = relationship(back_populates="features")
    tasks: Mapped[list[Task]] = relationship(
        back_populates="feature", cascade="all, delete-orphan"
    )


class FeatureDependency(Base):
    __tablename__ = "feature_dependencies"

    feature_id: Mapped[_uuid.UUID] = mapped_column(
        ForeignKey("features.id"), primary_key=True
    )
    depends_on_id: Mapped[_uuid.UUID] = mapped_column(
        ForeignKey("features.id"), primary_key=True
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    feature_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("features.id"))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="backlog")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    worktree_id: Mapped[_uuid.UUID | None] = mapped_column(default=None)
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    feature: Mapped[Feature] = relationship(back_populates="tasks")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test-board`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/board/models.py tests/board/test_models.py
git commit -m "feat(board): add SQLAlchemy models for Project, Epic, Feature, Task"
```

---

### Task 2: Pydantic Schemas

**Files:**
- Create: `src/board/schemas.py`

- [ ] **Step 1: Create schemas**

```python
# src/board/schemas.py
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
    created_at: datetime
    updated_at: datetime


# --- Board view ---

class TaskCard(TaskResponse):
    """Task with breadcrumb info for the Kanban board."""
    epic_title: str = ""
    feature_title: str = ""


class BoardColumn(BaseModel):
    status: str
    tasks: list[TaskCard]


class BoardResponse(BaseModel):
    project_id: UUID
    project_name: str
    columns: list[BoardColumn]
    total_tasks: int
    done_count: int


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
```

- [ ] **Step 2: Verify types pass**

Run: `cd /home/sachin/code/cloglog && python -m mypy src/board/schemas.py --no-error-summary`
Expected: Success with no errors.

- [ ] **Step 3: Commit**

```bash
git add src/board/schemas.py
git commit -m "feat(board): add Pydantic schemas for all Board entities"
```

---

### Task 3: Repository Layer

**Files:**
- Create: `src/board/repository.py`
- Test: `tests/board/test_repository.py`

- [ ] **Step 1: Write repository tests**

```python
# tests/board/test_repository.py
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Epic, Feature, Project, Task
from src.board.repository import BoardRepository


@pytest.fixture
def repo(db_session: AsyncSession) -> BoardRepository:
    return BoardRepository(db_session)


@pytest.fixture
async def sample_project(db_session: AsyncSession) -> Project:
    project = Project(name="repo-test-project")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


# --- Project ---

async def test_create_project(repo: BoardRepository):
    project = await repo.create_project("new-project", "desc", "")
    assert project.name == "new-project"
    assert project.id is not None


async def test_get_project(repo: BoardRepository, sample_project: Project):
    project = await repo.get_project(sample_project.id)
    assert project is not None
    assert project.name == "repo-test-project"


async def test_list_projects(repo: BoardRepository, sample_project: Project):
    projects = await repo.list_projects()
    assert len(projects) >= 1
    assert any(p.name == "repo-test-project" for p in projects)


# --- Epic ---

async def test_create_epic(repo: BoardRepository, sample_project: Project):
    epic = await repo.create_epic(sample_project.id, "Test Epic", "", "", "", 0)
    assert epic.title == "Test Epic"
    assert epic.project_id == sample_project.id


async def test_list_epics(repo: BoardRepository, sample_project: Project):
    await repo.create_epic(sample_project.id, "Epic 1", "", "", "", 0)
    await repo.create_epic(sample_project.id, "Epic 2", "", "", "", 1)
    epics = await repo.list_epics(sample_project.id)
    assert len(epics) == 2


# --- Feature ---

async def test_create_feature(repo: BoardRepository, sample_project: Project):
    epic = await repo.create_epic(sample_project.id, "Epic", "", "", "", 0)
    feature = await repo.create_feature(epic.id, "Test Feature", "", 0)
    assert feature.title == "Test Feature"


# --- Task ---

async def test_create_task(repo: BoardRepository, sample_project: Project):
    epic = await repo.create_epic(sample_project.id, "Epic", "", "", "", 0)
    feature = await repo.create_feature(epic.id, "Feature", "", 0)
    task = await repo.create_task(feature.id, "Test Task", "", "normal", 0)
    assert task.title == "Test Task"
    assert task.status == "backlog"


async def test_update_task(repo: BoardRepository, sample_project: Project):
    epic = await repo.create_epic(sample_project.id, "Epic", "", "", "", 0)
    feature = await repo.create_feature(epic.id, "Feature", "", 0)
    task = await repo.create_task(feature.id, "Task", "", "normal", 0)
    updated = await repo.update_task(task.id, status="in_progress")
    assert updated is not None
    assert updated.status == "in_progress"


async def test_delete_task(repo: BoardRepository, sample_project: Project):
    epic = await repo.create_epic(sample_project.id, "Epic", "", "", "", 0)
    feature = await repo.create_feature(epic.id, "Feature", "", 0)
    task = await repo.create_task(feature.id, "Task", "", "normal", 0)
    deleted = await repo.delete_task(task.id)
    assert deleted is True
    assert await repo.get_task(task.id) is None


# --- Board query ---

async def test_get_board_tasks(repo: BoardRepository, sample_project: Project):
    epic = await repo.create_epic(sample_project.id, "Epic", "", "", "", 0)
    feature = await repo.create_feature(epic.id, "Feature", "", 0)
    await repo.create_task(feature.id, "Task 1", "", "normal", 0)
    await repo.create_task(feature.id, "Task 2", "", "normal", 1)
    tasks = await repo.get_board_tasks(sample_project.id)
    assert len(tasks) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-board`
Expected: ImportError — `src.board.repository` does not exist.

- [ ] **Step 3: Implement repository**

```python
# src/board/repository.py
"""Database queries for the Board bounded context."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.board.models import Epic, Feature, Project, Task


class BoardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Project ---

    async def create_project(
        self, name: str, description: str, repo_url: str
    ) -> Project:
        project = Project(name=name, description=description, repo_url=repo_url)
        self._session.add(project)
        await self._session.commit()
        await self._session.refresh(project)
        return project

    async def get_project(self, project_id: UUID) -> Project | None:
        return await self._session.get(Project, project_id)

    async def list_projects(self) -> list[Project]:
        result = await self._session.execute(
            select(Project).order_by(Project.created_at)
        )
        return list(result.scalars().all())

    async def set_project_api_key_hash(
        self, project_id: UUID, api_key_hash: str
    ) -> None:
        project = await self._session.get(Project, project_id)
        if project:
            project.api_key_hash = api_key_hash
            await self._session.commit()

    async def get_project_by_api_key_hash(self, api_key_hash: str) -> Project | None:
        result = await self._session.execute(
            select(Project).where(Project.api_key_hash == api_key_hash)
        )
        return result.scalar_one_or_none()

    # --- Epic ---

    async def create_epic(
        self,
        project_id: UUID,
        title: str,
        description: str,
        bounded_context: str,
        context_description: str,
        position: int,
    ) -> Epic:
        epic = Epic(
            project_id=project_id,
            title=title,
            description=description,
            bounded_context=bounded_context,
            context_description=context_description,
            position=position,
        )
        self._session.add(epic)
        await self._session.commit()
        await self._session.refresh(epic)
        return epic

    async def list_epics(self, project_id: UUID) -> list[Epic]:
        result = await self._session.execute(
            select(Epic)
            .where(Epic.project_id == project_id)
            .order_by(Epic.position)
        )
        return list(result.scalars().all())

    async def get_epic(self, epic_id: UUID) -> Epic | None:
        return await self._session.get(Epic, epic_id)

    # --- Feature ---

    async def create_feature(
        self, epic_id: UUID, title: str, description: str, position: int
    ) -> Feature:
        feature = Feature(
            epic_id=epic_id, title=title, description=description, position=position
        )
        self._session.add(feature)
        await self._session.commit()
        await self._session.refresh(feature)
        return feature

    async def list_features(self, epic_id: UUID) -> list[Feature]:
        result = await self._session.execute(
            select(Feature)
            .where(Feature.epic_id == epic_id)
            .order_by(Feature.position)
        )
        return list(result.scalars().all())

    async def get_feature(self, feature_id: UUID) -> Feature | None:
        return await self._session.get(Feature, feature_id)

    # --- Task ---

    async def create_task(
        self,
        feature_id: UUID,
        title: str,
        description: str,
        priority: str,
        position: int,
    ) -> Task:
        task = Task(
            feature_id=feature_id,
            title=title,
            description=description,
            priority=priority,
            position=position,
        )
        self._session.add(task)
        await self._session.commit()
        await self._session.refresh(task)
        return task

    async def get_task(self, task_id: UUID) -> Task | None:
        return await self._session.get(Task, task_id)

    async def update_task(self, task_id: UUID, **fields: object) -> Task | None:
        task = await self._session.get(Task, task_id)
        if task is None:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(task, key, value)
        await self._session.commit()
        await self._session.refresh(task)
        return task

    async def delete_task(self, task_id: UUID) -> bool:
        task = await self._session.get(Task, task_id)
        if task is None:
            return False
        await self._session.delete(task)
        await self._session.commit()
        return True

    async def get_board_tasks(self, project_id: UUID) -> list[Task]:
        """Get all tasks for a project with their feature/epic info loaded."""
        result = await self._session.execute(
            select(Task)
            .join(Feature, Task.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Epic.project_id == project_id)
            .options(joinedload(Task.feature).joinedload(Feature.epic))
            .order_by(Task.position)
        )
        return list(result.unique().scalars().all())

    async def get_tasks_for_feature(self, feature_id: UUID) -> list[Task]:
        result = await self._session.execute(
            select(Task)
            .where(Task.feature_id == feature_id)
            .order_by(Task.position)
        )
        return list(result.scalars().all())

    async def get_tasks_for_worktree(self, worktree_id: UUID) -> list[Task]:
        result = await self._session.execute(
            select(Task)
            .where(Task.worktree_id == worktree_id)
            .order_by(Task.position)
        )
        return list(result.scalars().all())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test-board`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/board/repository.py tests/board/test_repository.py
git commit -m "feat(board): add repository layer with CRUD for all entities"
```

---

### Task 4: Services — API Key, Roll-Up, Import

**Files:**
- Create: `src/board/services.py`
- Test: `tests/board/test_services.py`

- [ ] **Step 1: Write service tests**

```python
# tests/board/test_services.py
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Epic, Feature, Project, Task
from src.board.repository import BoardRepository
from src.board.schemas import ImportPlan
from src.board.services import BoardService


@pytest.fixture
def service(db_session: AsyncSession) -> BoardService:
    return BoardService(BoardRepository(db_session))


# --- API Key ---

async def test_create_project_with_api_key(service: BoardService):
    project, api_key = await service.create_project("key-test", "", "")
    assert project.name == "key-test"
    assert len(api_key) == 64  # hex-encoded 32 bytes
    assert project.api_key_hash != ""
    assert project.api_key_hash != api_key  # stored hashed, not plain


async def test_verify_api_key(service: BoardService):
    project, api_key = await service.create_project("verify-test", "", "")
    verified = await service.verify_api_key(api_key)
    assert verified is not None
    assert verified.id == project.id


async def test_verify_bad_api_key(service: BoardService):
    await service.create_project("bad-key-test", "", "")
    verified = await service.verify_api_key("not-a-real-key")
    assert verified is None


# --- Status Roll-Up ---

async def test_rollup_feature_all_done(service: BoardService, db_session: AsyncSession):
    project, _ = await service.create_project("rollup-test", "", "")
    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    t1 = Task(feature_id=feature.id, title="T1", status="done", position=0)
    t2 = Task(feature_id=feature.id, title="T2", status="done", position=1)
    db_session.add_all([t1, t2])
    await db_session.commit()

    await service.recompute_rollup(feature.id)
    await db_session.refresh(feature)
    await db_session.refresh(epic)
    assert feature.status == "done"
    assert epic.status == "done"


async def test_rollup_feature_in_progress(service: BoardService, db_session: AsyncSession):
    project, _ = await service.create_project("rollup-ip-test", "", "")
    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    t1 = Task(feature_id=feature.id, title="T1", status="in_progress", position=0)
    t2 = Task(feature_id=feature.id, title="T2", status="backlog", position=1)
    db_session.add_all([t1, t2])
    await db_session.commit()

    await service.recompute_rollup(feature.id)
    await db_session.refresh(feature)
    assert feature.status == "in_progress"


async def test_rollup_feature_in_review(service: BoardService, db_session: AsyncSession):
    project, _ = await service.create_project("rollup-review-test", "", "")
    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    t1 = Task(feature_id=feature.id, title="T1", status="review", position=0)
    t2 = Task(feature_id=feature.id, title="T2", status="done", position=1)
    db_session.add_all([t1, t2])
    await db_session.commit()

    await service.recompute_rollup(feature.id)
    await db_session.refresh(feature)
    assert feature.status == "review"


# --- Import ---

async def test_import_plan(service: BoardService):
    project, _ = await service.create_project("import-test", "", "")
    plan = ImportPlan(epics=[
        {
            "title": "Auth Epic",
            "features": [
                {
                    "title": "Login",
                    "tasks": [
                        {"title": "Login form"},
                        {"title": "Login API"},
                    ],
                }
            ],
        }
    ])
    result = await service.import_plan(project.id, plan)
    assert result["epics_created"] == 1
    assert result["features_created"] == 1
    assert result["tasks_created"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-board`
Expected: ImportError — `src.board.services` does not exist.

- [ ] **Step 3: Implement services**

```python
# src/board/services.py
"""Business logic for the Board bounded context."""

from __future__ import annotations

import hashlib
import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Epic, Feature, Project, Task
from src.board.repository import BoardRepository
from src.board.schemas import ImportPlan


class BoardService:
    def __init__(self, repo: BoardRepository) -> None:
        self._repo = repo

    # --- API Key ---

    async def create_project(
        self, name: str, description: str, repo_url: str
    ) -> tuple[Project, str]:
        """Create a project and return (project, plaintext_api_key)."""
        project = await self._repo.create_project(name, description, repo_url)
        api_key = secrets.token_hex(32)
        api_key_hash = self._hash_key(api_key)
        await self._repo.set_project_api_key_hash(project.id, api_key_hash)
        # Refresh to get the updated hash
        project = await self._repo.get_project(project.id)
        assert project is not None
        return project, api_key

    async def verify_api_key(self, api_key: str) -> Project | None:
        """Verify an API key and return the associated project."""
        api_key_hash = self._hash_key(api_key)
        return await self._repo.get_project_by_api_key_hash(api_key_hash)

    @staticmethod
    def _hash_key(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    # --- Status Roll-Up ---

    async def recompute_rollup(self, feature_id: UUID) -> None:
        """Recompute feature status from tasks, then epic status from features."""
        tasks = await self._repo.get_tasks_for_feature(feature_id)
        feature = await self._repo.get_feature(feature_id)
        if feature is None:
            return

        # Feature status roll-up from tasks
        statuses = [t.status for t in tasks]
        if all(s == "done" for s in statuses):
            feature.status = "done"
        elif any(s == "review" for s in statuses):
            feature.status = "review"
        elif any(s in ("in_progress", "assigned") for s in statuses):
            feature.status = "in_progress"
        else:
            feature.status = "planned"

        session = self._repo._session
        await session.commit()

        # Epic status roll-up from features
        epic = await self._repo.get_epic(feature.epic_id)
        if epic is None:
            return

        features = await self._repo.list_features(epic.id)
        feature_statuses = [f.status for f in features]
        if all(s == "done" for s in feature_statuses):
            epic.status = "done"
        elif any(s in ("in_progress", "review") for s in feature_statuses):
            epic.status = "in_progress"
        else:
            epic.status = "planned"

        await session.commit()

    # --- Import ---

    async def import_plan(
        self, project_id: UUID, plan: ImportPlan
    ) -> dict[str, int]:
        """Bulk import epics/features/tasks from a structured plan."""
        epics_created = 0
        features_created = 0
        tasks_created = 0

        for epic_pos, epic_data in enumerate(plan.epics):
            epic = await self._repo.create_epic(
                project_id=project_id,
                title=epic_data.title,
                description=epic_data.description,
                bounded_context=epic_data.bounded_context,
                context_description="",
                position=epic_pos,
            )
            epics_created += 1

            for feat_pos, feat_data in enumerate(epic_data.features):
                feature = await self._repo.create_feature(
                    epic_id=epic.id,
                    title=feat_data.title,
                    description=feat_data.description,
                    position=feat_pos,
                )
                features_created += 1

                for task_pos, task_data in enumerate(feat_data.tasks):
                    await self._repo.create_task(
                        feature_id=feature.id,
                        title=task_data.title,
                        description=task_data.description,
                        priority=task_data.priority,
                        position=task_pos,
                    )
                    tasks_created += 1

        return {
            "epics_created": epics_created,
            "features_created": features_created,
            "tasks_created": tasks_created,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test-board`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/board/services.py tests/board/test_services.py
git commit -m "feat(board): add services — API key gen, status roll-up, plan import"
```

---

### Task 5: API Routes

**Files:**
- Create: `src/board/routes.py`
- Test: `tests/board/test_routes.py`

- [ ] **Step 1: Write route integration tests**

```python
# tests/board/test_routes.py
import pytest
from httpx import AsyncClient


# --- Project endpoints ---

async def test_create_project(client: AsyncClient):
    resp = await client.post("/api/v1/projects", json={"name": "route-test"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "route-test"
    assert "api_key" in data
    assert len(data["api_key"]) == 64


async def test_list_projects(client: AsyncClient):
    await client.post("/api/v1/projects", json={"name": "list-test-1"})
    await client.post("/api/v1/projects", json={"name": "list-test-2"})
    resp = await client.get("/api/v1/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2


async def test_get_project(client: AsyncClient):
    create_resp = await client.post("/api/v1/projects", json={"name": "get-test"})
    project_id = create_resp.json()["id"]
    resp = await client.get(f"/api/v1/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "get-test"


async def test_get_project_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


# --- Epic endpoints ---

async def test_create_epic(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "epic-test"})).json()
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/epics",
        json={"title": "Auth Epic"},
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "Auth Epic"


async def test_list_epics(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "epic-list-test"})).json()
    await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "E1"})
    await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "E2"})
    resp = await client.get(f"/api/v1/projects/{project['id']}/epics")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


# --- Feature endpoints ---

async def test_create_feature(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "feat-test"})).json()
    epic = (await client.post(
        f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"}
    )).json()
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
        json={"title": "Login Feature"},
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "Login Feature"


# --- Task endpoints ---

async def test_create_task(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "task-test"})).json()
    epic = (await client.post(
        f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"}
    )).json()
    feature = (await client.post(
        f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
        json={"title": "Feature"},
    )).json()
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Write tests"},
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "Write tests"
    assert resp.json()["status"] == "backlog"


async def test_update_task(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "task-update-test"})).json()
    epic = (await client.post(
        f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"}
    )).json()
    feature = (await client.post(
        f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
        json={"title": "Feature"},
    )).json()
    task = (await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Task"},
    )).json()
    resp = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"status": "in_progress"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


async def test_delete_task(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "task-del-test"})).json()
    epic = (await client.post(
        f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"}
    )).json()
    feature = (await client.post(
        f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
        json={"title": "Feature"},
    )).json()
    task = (await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Task"},
    )).json()
    resp = await client.delete(f"/api/v1/tasks/{task['id']}")
    assert resp.status_code == 204


# --- Board endpoint ---

async def test_get_board(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "board-test"})).json()
    epic = (await client.post(
        f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"}
    )).json()
    feature = (await client.post(
        f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
        json={"title": "Feature"},
    )).json()
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "T1"},
    )
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "T2"},
    )
    resp = await client.get(f"/api/v1/projects/{project['id']}/board")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tasks"] == 2
    assert data["done_count"] == 0
    # Find the backlog column
    backlog = next(c for c in data["columns"] if c["status"] == "backlog")
    assert len(backlog["tasks"]) == 2


# --- Import endpoint ---

async def test_import_plan(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "import-test"})).json()
    plan = {
        "epics": [
            {
                "title": "Backend",
                "features": [
                    {
                        "title": "Auth",
                        "tasks": [
                            {"title": "Login"},
                            {"title": "Signup"},
                        ],
                    },
                    {
                        "title": "API",
                        "tasks": [
                            {"title": "REST endpoints"},
                        ],
                    },
                ],
            }
        ]
    }
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/import",
        json=plan,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["epics_created"] == 1
    assert data["features_created"] == 2
    assert data["tasks_created"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-board`
Expected: ImportError — `src.board.routes` does not exist.

- [ ] **Step 3: Implement routes**

```python
# src/board/routes.py
"""FastAPI routes for the Board bounded context."""

from __future__ import annotations

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
from src.board.services import BoardService
from src.shared.database import get_session

router = APIRouter()

BOARD_COLUMNS = ["backlog", "assigned", "in_progress", "review", "done", "blocked"]


def _get_service(session: AsyncSession = Depends(get_session)) -> BoardService:
    return BoardService(BoardRepository(session))


# --- Projects ---


@router.post("/projects", response_model=ProjectWithKey, status_code=201)
async def create_project(
    body: ProjectCreate, service: BoardService = Depends(_get_service)
) -> dict[str, object]:
    project, api_key = await service.create_project(
        body.name, body.description, body.repo_url
    )
    return {
        **ProjectResponse.model_validate(project).model_dump(),
        "api_key": api_key,
    }


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    service: BoardService = Depends(_get_service),
) -> list[ProjectResponse]:
    projects = await service._repo.list_projects()
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID, service: BoardService = Depends(_get_service)
) -> ProjectResponse:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)


# --- Epics ---


@router.post(
    "/projects/{project_id}/epics", response_model=EpicResponse, status_code=201
)
async def create_epic(
    project_id: UUID,
    body: EpicCreate,
    service: BoardService = Depends(_get_service),
) -> EpicResponse:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    epic = await service._repo.create_epic(
        project_id, body.title, body.description,
        body.bounded_context, body.context_description, body.position,
    )
    return EpicResponse.model_validate(epic)


@router.get(
    "/projects/{project_id}/epics", response_model=list[EpicResponse]
)
async def list_epics(
    project_id: UUID, service: BoardService = Depends(_get_service)
) -> list[EpicResponse]:
    epics = await service._repo.list_epics(project_id)
    return [EpicResponse.model_validate(e) for e in epics]


# --- Features ---


@router.post(
    "/projects/{project_id}/epics/{epic_id}/features",
    response_model=FeatureResponse,
    status_code=201,
)
async def create_feature(
    project_id: UUID,
    epic_id: UUID,
    body: FeatureCreate,
    service: BoardService = Depends(_get_service),
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
    project_id: UUID,
    epic_id: UUID,
    service: BoardService = Depends(_get_service),
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
    project_id: UUID,
    feature_id: UUID,
    body: TaskCreate,
    service: BoardService = Depends(_get_service),
) -> TaskResponse:
    feature = await service._repo.get_feature(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    task = await service._repo.create_task(
        feature_id, body.title, body.description, body.priority, body.position
    )
    return TaskResponse.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    body: TaskUpdate,
    service: BoardService = Depends(_get_service),
) -> TaskResponse:
    fields = body.model_dump(exclude_unset=True)
    task = await service._repo.update_task(task_id, **fields)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    # Trigger roll-up if status changed
    if "status" in fields:
        await service.recompute_rollup(task.feature_id)
    return TaskResponse.model_validate(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: UUID, service: BoardService = Depends(_get_service)
) -> None:
    deleted = await service._repo.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")


# --- Board ---


@router.get("/projects/{project_id}/board", response_model=BoardResponse)
async def get_board(
    project_id: UUID, service: BoardService = Depends(_get_service)
) -> BoardResponse:
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
async def import_plan(
    project_id: UUID,
    body: ImportPlan,
    service: BoardService = Depends(_get_service),
) -> dict[str, int]:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return await service.import_plan(project_id, body)
```

- [ ] **Step 4: Register router in gateway app**

Add the board router to `src/gateway/app.py`. Change the commented-out line:

```python
# In src/gateway/app.py, replace:
#     # Context routes will be included here in Phase 1:
#     # app.include_router(board_router, prefix="/api/v1")
# With:
    from src.board.routes import router as board_router
    app.include_router(board_router, prefix="/api/v1")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `make test-board`
Expected: All tests pass.

- [ ] **Step 6: Run full quality gate**

Run: `make quality`
Expected: lint, typecheck, and all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/board/routes.py tests/board/test_routes.py src/gateway/app.py
git commit -m "feat(board): add API routes for all Board context endpoints"
```

---

### Task 6: Delete Placeholder Test

**Files:**
- Modify: `tests/board/test_placeholder.py`

- [ ] **Step 1: Remove the placeholder test**

Delete `tests/board/test_placeholder.py` — it's been superseded by real tests.

```bash
rm tests/board/test_placeholder.py
```

- [ ] **Step 2: Verify tests still pass**

Run: `make test-board`

- [ ] **Step 3: Commit**

```bash
git add -A tests/board/test_placeholder.py
git commit -m "chore(board): remove placeholder test"
```

---

### Task 7: Alembic Migration

**Files:**
- Create: migration file in `src/alembic/versions/`

- [ ] **Step 1: Generate migration**

```bash
cd /home/sachin/code/cloglog
python -m alembic revision --autogenerate -m "board_context_tables"
```

- [ ] **Step 2: Review the generated migration**

Open the generated file in `src/alembic/versions/` and verify it creates tables: `projects`, `epics`, `features`, `feature_dependencies`, `tasks`.

- [ ] **Step 3: Run migration against dev database**

```bash
make db-up
make db-migrate
```

- [ ] **Step 4: Commit**

```bash
git add src/alembic/versions/
git commit -m "feat(board): add Alembic migration for Board context tables"
```

---

### Task 8: Final Quality Gate

- [ ] **Step 1: Run full quality gate**

Run: `make quality`
Expected: All checks pass — lint clean, type check clean, all tests green.

- [ ] **Step 2: Verify test count**

Run: `make test-board`
Expected: 20+ tests passing in `tests/board/`.
