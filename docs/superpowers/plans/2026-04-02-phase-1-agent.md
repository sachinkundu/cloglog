# Phase 1: Agent Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Agent bounded context — Worktree and Session models, agent registration (upsert), heartbeat, task lifecycle (start/complete/status update), and all agent-facing API routes.

**Architecture:** Agent context owns 2 tables (worktrees, sessions). It uses Board's `TaskAssignmentService` and `TaskStatusService` interfaces to manage task state. Agent routes are auth-protected (API key required).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Pydantic v2, pytest

**Worktree:** `wt-agent` — only touch `src/agent/`, `tests/agent/`, `src/alembic/`

**Dependency:** Board context must be merged first (Agent calls Board's TaskStatusService and TaskAssignmentService).

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/agent/models.py` | SQLAlchemy models: Worktree, Session |
| `src/agent/schemas.py` | Pydantic request/response schemas |
| `src/agent/repository.py` | DB queries for worktrees and sessions |
| `src/agent/services.py` | Registration, heartbeat, task lifecycle logic |
| `src/agent/routes.py` | FastAPI router for agent-facing endpoints |
| `src/agent/interfaces.py` | Already exists — WorktreeService protocol |
| `tests/agent/test_models.py` | Model creation tests |
| `tests/agent/test_services.py` | Registration logic, heartbeat, reconnection tests |
| `tests/agent/test_routes.py` | Integration tests for all agent endpoints |

---

### Task 1: SQLAlchemy Models

**Files:**
- Create: `src/agent/models.py`
- Test: `tests/agent/test_models.py`

- [ ] **Step 1: Write model tests**

```python
# tests/agent/test_models.py
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.models import Session, Worktree
from src.board.models import Project


async def test_create_worktree(db_session: AsyncSession):
    project = Project(name="agent-model-test")
    db_session.add(project)
    await db_session.flush()

    wt = Worktree(
        project_id=project.id,
        name="wt-auth",
        worktree_path="/home/user/project/wt-auth",
    )
    db_session.add(wt)
    await db_session.commit()

    result = await db_session.execute(select(Worktree).where(Worktree.name == "wt-auth"))
    row = result.scalar_one()
    assert row.status == "idle"
    assert row.current_task_id is None


async def test_create_session(db_session: AsyncSession):
    project = Project(name="session-model-test")
    db_session.add(project)
    await db_session.flush()

    wt = Worktree(
        project_id=project.id, name="wt-api",
        worktree_path="/home/user/project/wt-api",
    )
    db_session.add(wt)
    await db_session.flush()

    session = Session(worktree_id=wt.id)
    db_session.add(session)
    await db_session.commit()

    result = await db_session.execute(select(Session).where(Session.worktree_id == wt.id))
    row = result.scalar_one()
    assert row.started_at is not None
    assert row.ended_at is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-agent`
Expected: ImportError — `src.agent.models` does not exist.

- [ ] **Step 3: Implement models**

```python
# src/agent/models.py
"""SQLAlchemy models for the Agent bounded context."""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.database import Base


class Worktree(Base):
    __tablename__ = "worktrees"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(255))
    worktree_path: Mapped[str] = mapped_column(String(500))
    current_task_id: Mapped[_uuid.UUID | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String(20), default="idle")
    last_heartbeat: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    sessions: Mapped[list[Session]] = relationship(
        back_populates="worktree", cascade="all, delete-orphan"
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    worktree_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("worktrees.id"))
    started_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    ended_at: Mapped[datetime | None] = mapped_column(default=None)

    worktree: Mapped[Worktree] = relationship(back_populates="sessions")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test-agent`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent/models.py tests/agent/test_models.py
git commit -m "feat(agent): add Worktree and Session SQLAlchemy models"
```

---

### Task 2: Schemas

**Files:**
- Create: `src/agent/schemas.py`

- [ ] **Step 1: Create schemas**

```python
# src/agent/schemas.py
"""Pydantic schemas for the Agent context API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RegisterRequest(BaseModel):
    worktree_path: str


class RegisterResponse(BaseModel):
    worktree_id: UUID
    name: str
    current_task: dict | None = None
    resumed: bool = False


class HeartbeatResponse(BaseModel):
    status: str = "ok"


class StartTaskRequest(BaseModel):
    task_id: UUID


class CompleteTaskRequest(BaseModel):
    task_id: UUID


class CompleteTaskResponse(BaseModel):
    completed_task_id: UUID
    next_task: dict | None = None


class UpdateTaskStatusRequest(BaseModel):
    task_id: UUID
    status: str


class TaskNoteRequest(BaseModel):
    task_id: UUID
    note: str


class WorktreeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    worktree_path: str
    current_task_id: UUID | None
    status: str
    last_heartbeat: datetime
    created_at: datetime
```

- [ ] **Step 2: Verify types**

Run: `python -m mypy src/agent/schemas.py --no-error-summary`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add src/agent/schemas.py
git commit -m "feat(agent): add Pydantic schemas"
```

---

### Task 3: Repository

**Files:**
- Create: `src/agent/repository.py`
- Test: `tests/agent/test_repository.py`

- [ ] **Step 1: Write repository tests**

```python
# tests/agent/test_repository.py
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.models import Worktree
from src.agent.repository import AgentRepository
from src.board.models import Project


@pytest.fixture
def repo(db_session: AsyncSession) -> AgentRepository:
    return AgentRepository(db_session)


@pytest.fixture
async def sample_project(db_session: AsyncSession) -> Project:
    project = Project(name="agent-repo-test")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def test_upsert_worktree_new(repo: AgentRepository, sample_project: Project):
    wt, created = await repo.upsert_worktree(
        sample_project.id, "/home/user/wt-new"
    )
    assert created is True
    assert wt.name == "wt-new"
    assert wt.status == "active"


async def test_upsert_worktree_existing(repo: AgentRepository, sample_project: Project):
    wt1, _ = await repo.upsert_worktree(sample_project.id, "/home/user/wt-exist")
    wt2, created = await repo.upsert_worktree(sample_project.id, "/home/user/wt-exist")
    assert created is False
    assert wt1.id == wt2.id
    assert wt2.status == "active"


async def test_create_session(repo: AgentRepository, sample_project: Project):
    wt, _ = await repo.upsert_worktree(sample_project.id, "/home/user/wt-sess")
    session = await repo.create_session(wt.id)
    assert session.worktree_id == wt.id
    assert session.ended_at is None


async def test_update_heartbeat(repo: AgentRepository, sample_project: Project):
    wt, _ = await repo.upsert_worktree(sample_project.id, "/home/user/wt-hb")
    old_hb = wt.last_heartbeat
    await repo.update_heartbeat(wt.id)
    updated = await repo.get_worktree(wt.id)
    assert updated is not None
    assert updated.last_heartbeat >= old_hb


async def test_list_worktrees(repo: AgentRepository, sample_project: Project):
    await repo.upsert_worktree(sample_project.id, "/home/user/wt-list-1")
    await repo.upsert_worktree(sample_project.id, "/home/user/wt-list-2")
    worktrees = await repo.list_worktrees(sample_project.id)
    assert len(worktrees) >= 2


async def test_set_idle(repo: AgentRepository, sample_project: Project):
    wt, _ = await repo.upsert_worktree(sample_project.id, "/home/user/wt-idle")
    assert wt.status == "active"
    await repo.set_worktree_idle(wt.id)
    updated = await repo.get_worktree(wt.id)
    assert updated is not None
    assert updated.status == "idle"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-agent`
Expected: ImportError — `src.agent.repository` does not exist.

- [ ] **Step 3: Implement repository**

```python
# src/agent/repository.py
"""Database queries for the Agent bounded context."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.models import Session, Worktree


class AgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_worktree(
        self, project_id: UUID, worktree_path: str
    ) -> tuple[Worktree, bool]:
        """Find or create a worktree by project + path. Returns (worktree, was_created)."""
        result = await self._session.execute(
            select(Worktree).where(
                Worktree.project_id == project_id,
                Worktree.worktree_path == worktree_path,
            )
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.status = "active"
            existing.last_heartbeat = datetime.now(timezone.utc)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing, False

        name = os.path.basename(worktree_path)
        wt = Worktree(
            project_id=project_id,
            name=name,
            worktree_path=worktree_path,
            status="active",
        )
        self._session.add(wt)
        await self._session.commit()
        await self._session.refresh(wt)
        return wt, True

    async def get_worktree(self, worktree_id: UUID) -> Worktree | None:
        return await self._session.get(Worktree, worktree_id)

    async def list_worktrees(self, project_id: UUID) -> list[Worktree]:
        result = await self._session.execute(
            select(Worktree)
            .where(Worktree.project_id == project_id)
            .order_by(Worktree.created_at)
        )
        return list(result.scalars().all())

    async def update_heartbeat(self, worktree_id: UUID) -> None:
        wt = await self._session.get(Worktree, worktree_id)
        if wt:
            wt.last_heartbeat = datetime.now(timezone.utc)
            await self._session.commit()

    async def set_worktree_status(self, worktree_id: UUID, status: str) -> None:
        wt = await self._session.get(Worktree, worktree_id)
        if wt:
            wt.status = status
            await self._session.commit()

    async def set_worktree_idle(self, worktree_id: UUID) -> None:
        await self.set_worktree_status(worktree_id, "idle")

    async def set_current_task(
        self, worktree_id: UUID, task_id: UUID | None
    ) -> None:
        wt = await self._session.get(Worktree, worktree_id)
        if wt:
            wt.current_task_id = task_id
            await self._session.commit()

    async def create_session(self, worktree_id: UUID) -> Session:
        session = Session(worktree_id=worktree_id)
        self._session.add(session)
        await self._session.commit()
        await self._session.refresh(session)
        return session

    async def end_session(self, worktree_id: UUID) -> None:
        """End the most recent active session for a worktree."""
        result = await self._session.execute(
            select(Session)
            .where(Session.worktree_id == worktree_id, Session.ended_at.is_(None))
            .order_by(Session.started_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()
        if session:
            session.ended_at = datetime.now(timezone.utc)
            await self._session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test-agent`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent/repository.py tests/agent/test_repository.py
git commit -m "feat(agent): add repository layer for worktrees and sessions"
```

---

### Task 4: Services

**Files:**
- Create: `src/agent/services.py`
- Test: `tests/agent/test_services.py`

- [ ] **Step 1: Write service tests**

```python
# tests/agent/test_services.py
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.repository import AgentRepository
from src.agent.services import AgentService
from src.board.models import Epic, Feature, Project, Task
from src.board.repository import BoardRepository
from src.board.services import BoardService


@pytest.fixture
async def setup(db_session: AsyncSession):
    """Create a project with a task and return all services + IDs."""
    project = Project(name="agent-svc-test")
    db_session.add(project)
    await db_session.flush()

    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    task = Task(feature_id=feature.id, title="Test task", position=0)
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(project)
    await db_session.refresh(task)

    board_repo = BoardRepository(db_session)
    board_service = BoardService(board_repo)
    agent_repo = AgentRepository(db_session)
    agent_service = AgentService(agent_repo, board_service)

    return {
        "agent_service": agent_service,
        "project": project,
        "task": task,
        "db_session": db_session,
    }


async def test_register_new_agent(setup):
    svc = setup["agent_service"]
    project = setup["project"]
    result = await svc.register(project.id, "/home/user/wt-new-agent")
    assert result["name"] == "wt-new-agent"
    assert result["resumed"] is False
    assert result["current_task"] is None


async def test_register_existing_agent_resumes(setup):
    svc = setup["agent_service"]
    project = setup["project"]
    task = setup["task"]

    # Register first time
    r1 = await svc.register(project.id, "/home/user/wt-resume")
    wt_id = r1["worktree_id"]

    # Assign a task to this worktree
    await svc._board_service._repo.update_task(task.id, worktree_id=wt_id)
    await svc._agent_repo.set_current_task(wt_id, task.id)

    # Unregister
    await svc.unregister(wt_id)

    # Re-register — should resume
    r2 = await svc.register(project.id, "/home/user/wt-resume")
    assert r2["resumed"] is True
    assert r2["worktree_id"] == wt_id


async def test_start_task(setup):
    svc = setup["agent_service"]
    project = setup["project"]
    task = setup["task"]

    result = await svc.register(project.id, "/home/user/wt-start")
    wt_id = result["worktree_id"]

    # Assign task to worktree first
    await svc._board_service._repo.update_task(task.id, worktree_id=wt_id)

    await svc.start_task(wt_id, task.id)

    # Verify task is in_progress
    updated_task = await svc._board_service._repo.get_task(task.id)
    assert updated_task is not None
    assert updated_task.status == "in_progress"


async def test_complete_task(setup):
    svc = setup["agent_service"]
    project = setup["project"]
    task = setup["task"]

    result = await svc.register(project.id, "/home/user/wt-complete")
    wt_id = result["worktree_id"]

    await svc._board_service._repo.update_task(task.id, worktree_id=wt_id)
    await svc.start_task(wt_id, task.id)
    completed = await svc.complete_task(wt_id, task.id)

    assert completed["completed_task_id"] == task.id

    updated_task = await svc._board_service._repo.get_task(task.id)
    assert updated_task is not None
    assert updated_task.status == "done"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-agent`
Expected: ImportError — `src.agent.services` does not exist.

- [ ] **Step 3: Implement services**

```python
# src/agent/services.py
"""Business logic for the Agent bounded context."""

from __future__ import annotations

from uuid import UUID

from src.agent.repository import AgentRepository
from src.board.services import BoardService
from src.shared.events import Event, EventType, event_bus


class AgentService:
    def __init__(
        self, agent_repo: AgentRepository, board_service: BoardService
    ) -> None:
        self._agent_repo = agent_repo
        self._board_service = board_service

    async def register(
        self, project_id: UUID, worktree_path: str
    ) -> dict:
        """Register or reconnect a worktree. Returns registration info."""
        wt, created = await self._agent_repo.upsert_worktree(project_id, worktree_path)
        await self._agent_repo.create_session(wt.id)

        # Check if there's a current task (resumption)
        current_task = None
        if wt.current_task_id is not None:
            task = await self._board_service._repo.get_task(wt.current_task_id)
            if task is not None:
                current_task = {
                    "task_id": str(task.id),
                    "title": task.title,
                    "status": task.status,
                }

        await event_bus.publish(Event(
            type=EventType.WORKTREE_ONLINE,
            project_id=project_id,
            data={"worktree_id": str(wt.id), "name": wt.name},
        ))

        return {
            "worktree_id": wt.id,
            "name": wt.name,
            "current_task": current_task,
            "resumed": not created,
        }

    async def heartbeat(self, worktree_id: UUID) -> None:
        await self._agent_repo.update_heartbeat(worktree_id)

    async def start_task(self, worktree_id: UUID, task_id: UUID) -> None:
        """Mark a task as in_progress and set it as the worktree's current task."""
        await self._board_service._repo.update_task(task_id, status="in_progress")
        await self._agent_repo.set_current_task(worktree_id, task_id)

        wt = await self._agent_repo.get_worktree(worktree_id)
        if wt:
            await self._board_service.recompute_rollup(
                (await self._board_service._repo.get_task(task_id)).feature_id  # type: ignore[union-attr]
            )
            await event_bus.publish(Event(
                type=EventType.TASK_STATUS_CHANGED,
                project_id=wt.project_id,
                data={"task_id": str(task_id), "status": "in_progress",
                       "worktree_id": str(worktree_id)},
            ))

    async def complete_task(
        self, worktree_id: UUID, task_id: UUID
    ) -> dict:
        """Complete a task, clear current_task, return next task if available."""
        await self._board_service._repo.update_task(task_id, status="done")
        await self._agent_repo.set_current_task(worktree_id, None)

        task = await self._board_service._repo.get_task(task_id)
        if task:
            await self._board_service.recompute_rollup(task.feature_id)

        wt = await self._agent_repo.get_worktree(worktree_id)
        if wt:
            await event_bus.publish(Event(
                type=EventType.TASK_STATUS_CHANGED,
                project_id=wt.project_id,
                data={"task_id": str(task_id), "status": "done",
                       "worktree_id": str(worktree_id)},
            ))

        # Find next assigned task
        next_task = None
        tasks = await self._board_service._repo.get_tasks_for_worktree(worktree_id)
        for t in tasks:
            if t.status in ("backlog", "assigned"):
                next_task = {"task_id": str(t.id), "title": t.title}
                break

        return {
            "completed_task_id": task_id,
            "next_task": next_task,
        }

    async def update_task_status(
        self, worktree_id: UUID, task_id: UUID, status: str
    ) -> None:
        """Move a task to a specific status column."""
        await self._board_service._repo.update_task(task_id, status=status)
        task = await self._board_service._repo.get_task(task_id)
        if task:
            await self._board_service.recompute_rollup(task.feature_id)

        wt = await self._agent_repo.get_worktree(worktree_id)
        if wt:
            await event_bus.publish(Event(
                type=EventType.TASK_STATUS_CHANGED,
                project_id=wt.project_id,
                data={"task_id": str(task_id), "status": status,
                       "worktree_id": str(worktree_id)},
            ))

    async def unregister(self, worktree_id: UUID) -> None:
        """End the current session and set worktree to idle."""
        await self._agent_repo.end_session(worktree_id)
        await self._agent_repo.set_worktree_idle(worktree_id)

        wt = await self._agent_repo.get_worktree(worktree_id)
        if wt:
            await event_bus.publish(Event(
                type=EventType.WORKTREE_OFFLINE,
                project_id=wt.project_id,
                data={"worktree_id": str(worktree_id), "name": wt.name},
            ))

    async def get_worktrees(self, project_id: UUID) -> list[dict]:
        worktrees = await self._agent_repo.list_worktrees(project_id)
        return [
            {
                "id": str(wt.id),
                "name": wt.name,
                "worktree_path": wt.worktree_path,
                "status": wt.status,
                "current_task_id": str(wt.current_task_id) if wt.current_task_id else None,
                "last_heartbeat": wt.last_heartbeat.isoformat(),
            }
            for wt in worktrees
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test-agent`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent/services.py tests/agent/test_services.py
git commit -m "feat(agent): add services — registration, heartbeat, task lifecycle"
```

---

### Task 5: API Routes

**Files:**
- Create: `src/agent/routes.py`
- Test: `tests/agent/test_routes.py`

- [ ] **Step 1: Write route tests**

```python
# tests/agent/test_routes.py
import pytest
from httpx import AsyncClient


@pytest.fixture
async def project_with_task(client: AsyncClient) -> dict:
    """Create a project, epic, feature, task. Return IDs + api_key."""
    p = (await client.post("/api/v1/projects", json={"name": "agent-route-test"})).json()
    e = (await client.post(
        f"/api/v1/projects/{p['id']}/epics", json={"title": "Epic"}
    )).json()
    f = (await client.post(
        f"/api/v1/projects/{p['id']}/epics/{e['id']}/features",
        json={"title": "Feature"},
    )).json()
    t = (await client.post(
        f"/api/v1/projects/{p['id']}/features/{f['id']}/tasks",
        json={"title": "Task"},
    )).json()
    return {"project_id": p["id"], "api_key": p["api_key"], "task_id": t["id"]}


def _auth(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


async def test_register_agent(client: AsyncClient, project_with_task: dict):
    resp = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/home/user/wt-test"},
        headers=_auth(project_with_task["api_key"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "wt-test"
    assert data["resumed"] is False


async def test_register_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/home/user/wt-noauth"},
    )
    assert resp.status_code == 401


async def test_heartbeat(client: AsyncClient, project_with_task: dict):
    reg = (await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/home/user/wt-hb"},
        headers=_auth(project_with_task["api_key"]),
    )).json()
    resp = await client.post(
        f"/api/v1/agents/{reg['worktree_id']}/heartbeat",
        headers=_auth(project_with_task["api_key"]),
    )
    assert resp.status_code == 200


async def test_start_and_complete_task(client: AsyncClient, project_with_task: dict):
    h = _auth(project_with_task["api_key"])
    task_id = project_with_task["task_id"]

    # Register
    reg = (await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/home/user/wt-lifecycle"},
        headers=h,
    )).json()
    wt_id = reg["worktree_id"]

    # Assign task to worktree
    await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"worktree_id": wt_id},
    )

    # Start task
    resp = await client.post(
        f"/api/v1/agents/{wt_id}/start-task",
        json={"task_id": task_id},
        headers=h,
    )
    assert resp.status_code == 200

    # Complete task
    resp = await client.post(
        f"/api/v1/agents/{wt_id}/complete-task",
        json={"task_id": task_id},
        headers=h,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["completed_task_id"] == task_id


async def test_unregister(client: AsyncClient, project_with_task: dict):
    h = _auth(project_with_task["api_key"])
    reg = (await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/home/user/wt-unreg"},
        headers=h,
    )).json()
    resp = await client.post(
        f"/api/v1/agents/{reg['worktree_id']}/unregister",
        headers=h,
    )
    assert resp.status_code == 200


async def test_get_worktrees(client: AsyncClient, project_with_task: dict):
    h = _auth(project_with_task["api_key"])
    await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/home/user/wt-list"},
        headers=h,
    )
    resp = await client.get(
        f"/api/v1/projects/{project_with_task['project_id']}/worktrees",
        headers=h,
    )
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-agent`
Expected: Fails — routes don't exist.

- [ ] **Step 3: Implement routes**

```python
# src/agent/routes.py
"""FastAPI routes for the Agent bounded context."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.repository import AgentRepository
from src.agent.schemas import (
    CompleteTaskRequest,
    CompleteTaskResponse,
    HeartbeatResponse,
    RegisterRequest,
    RegisterResponse,
    StartTaskRequest,
    UpdateTaskStatusRequest,
)
from src.agent.services import AgentService
from src.board.repository import BoardRepository
from src.board.services import BoardService
from src.gateway.auth import require_api_key
from src.shared.database import get_session

router = APIRouter()


def _get_agent_service(
    session: AsyncSession = Depends(get_session),
) -> AgentService:
    board_service = BoardService(BoardRepository(session))
    return AgentService(AgentRepository(session), board_service)


# --- Agent-facing endpoints (auth required) ---


@router.post(
    "/agents/register",
    response_model=RegisterResponse,
    dependencies=[Depends(require_api_key)],
)
async def register_agent(
    body: RegisterRequest,
    request: Request,
    service: AgentService = Depends(_get_agent_service),
) -> dict:
    project = request.state.project
    return await service.register(project.id, body.worktree_path)


@router.post(
    "/agents/{worktree_id}/heartbeat",
    response_model=HeartbeatResponse,
    dependencies=[Depends(require_api_key)],
)
async def heartbeat(
    worktree_id: UUID,
    service: AgentService = Depends(_get_agent_service),
) -> dict:
    await service.heartbeat(worktree_id)
    return {"status": "ok"}


@router.get(
    "/agents/{worktree_id}/tasks",
    dependencies=[Depends(require_api_key)],
)
async def get_agent_tasks(
    worktree_id: UUID,
    service: AgentService = Depends(_get_agent_service),
) -> list[dict]:
    tasks = await service._board_service._repo.get_tasks_for_worktree(worktree_id)
    return [
        {"task_id": str(t.id), "title": t.title, "description": t.description, "status": t.status}
        for t in tasks
    ]


@router.post(
    "/agents/{worktree_id}/start-task",
    dependencies=[Depends(require_api_key)],
)
async def start_task(
    worktree_id: UUID,
    body: StartTaskRequest,
    service: AgentService = Depends(_get_agent_service),
) -> dict:
    await service.start_task(worktree_id, body.task_id)
    return {"status": "ok"}


@router.post(
    "/agents/{worktree_id}/complete-task",
    response_model=CompleteTaskResponse,
    dependencies=[Depends(require_api_key)],
)
async def complete_task(
    worktree_id: UUID,
    body: CompleteTaskRequest,
    service: AgentService = Depends(_get_agent_service),
) -> dict:
    return await service.complete_task(worktree_id, body.task_id)


@router.patch(
    "/agents/{worktree_id}/task-status",
    dependencies=[Depends(require_api_key)],
)
async def update_task_status(
    worktree_id: UUID,
    body: UpdateTaskStatusRequest,
    service: AgentService = Depends(_get_agent_service),
) -> dict:
    await service.update_task_status(worktree_id, body.task_id, body.status)
    return {"status": "ok"}


@router.post(
    "/agents/{worktree_id}/unregister",
    dependencies=[Depends(require_api_key)],
)
async def unregister_agent(
    worktree_id: UUID,
    service: AgentService = Depends(_get_agent_service),
) -> dict:
    await service.unregister(worktree_id)
    return {"status": "ok"}


# --- Dashboard-facing endpoints ---


@router.get("/projects/{project_id}/worktrees")
async def list_worktrees(
    project_id: UUID,
    service: AgentService = Depends(_get_agent_service),
) -> list[dict]:
    return await service.get_worktrees(project_id)
```

- [ ] **Step 4: Register agent router in gateway app.py**

Add to `src/gateway/app.py` after the board router:

```python
    from src.agent.routes import router as agent_router
    app.include_router(agent_router, prefix="/api/v1")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `make test-agent`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/agent/routes.py tests/agent/test_routes.py src/gateway/app.py
git commit -m "feat(agent): add API routes for agent registration and task lifecycle"
```

---

### Task 6: Alembic Migration

**Files:**
- Create: migration file in `src/alembic/versions/`

- [ ] **Step 1: Generate migration**

```bash
cd /home/sachin/code/cloglog
python -m alembic revision --autogenerate -m "agent_context_tables"
```

- [ ] **Step 2: Review and run migration**

```bash
make db-up
make db-migrate
```

- [ ] **Step 3: Commit**

```bash
git add src/alembic/versions/
git commit -m "feat(agent): add Alembic migration for Worktree and Session tables"
```

---

### Task 7: Cleanup & Quality Gate

- [ ] **Step 1: Delete placeholder test**

```bash
rm -f tests/agent/test_placeholder.py
```

- [ ] **Step 2: Run full quality gate**

Run: `make quality`
Expected: All checks pass.

- [ ] **Step 3: Commit**

```bash
git add -A tests/agent/
git commit -m "chore(agent): remove placeholder test"
```
