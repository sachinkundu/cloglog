# Phase 1: Document Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Document bounded context — append-only document storage, attachment to Board entities (epic/feature/task), and retrieval endpoints.

**Architecture:** Document context owns 1 table (documents). Documents are write-once — never edited through the API. Each document references a Board entity via `attached_to_type` + `attached_to_id` (polymorphic, opaque — no FK constraint to Board tables). Agent-facing route for creating documents requires auth. Dashboard-facing routes for listing/reading are public.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Pydantic v2, pytest

**Worktree:** `wt-document` — only touch `src/document/`, `tests/document/`, `src/alembic/`

**Dependency:** Board context must be merged first (documents reference board entity IDs). Gateway auth module must exist.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/document/models.py` | SQLAlchemy model: Document |
| `src/document/schemas.py` | Pydantic request/response schemas |
| `src/document/repository.py` | DB queries for documents |
| `src/document/services.py` | Document creation, listing, retrieval |
| `src/document/routes.py` | FastAPI router — agent POST + dashboard GET |
| `src/document/interfaces.py` | Already exists — DocumentService protocol |
| `tests/document/test_models.py` | Model creation tests |
| `tests/document/test_routes.py` | Integration tests for all endpoints |

---

### Task 1: SQLAlchemy Model

**Files:**
- Create: `src/document/models.py`
- Test: `tests/document/test_models.py`

- [ ] **Step 1: Write model tests**

```python
# tests/document/test_models.py
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.document.models import Document


async def test_create_document(db_session: AsyncSession):
    doc = Document(
        type="spec",
        title="OAuth Flow Design",
        content="# OAuth Flow\n\nThis describes the auth flow.",
        source_path="docs/specs/oauth.md",
        attached_to_type="task",
        attached_to_id=uuid.uuid4(),
    )
    db_session.add(doc)
    await db_session.commit()

    result = await db_session.execute(
        select(Document).where(Document.title == "OAuth Flow Design")
    )
    row = result.scalar_one()
    assert row.type == "spec"
    assert row.content.startswith("# OAuth")
    assert row.attached_to_type == "task"


async def test_create_multiple_versions(db_session: AsyncSession):
    """Documents are append-only — same entity can have multiple docs."""
    entity_id = uuid.uuid4()

    doc1 = Document(
        type="spec", title="v1", content="first version",
        source_path="v1.md", attached_to_type="task", attached_to_id=entity_id,
    )
    doc2 = Document(
        type="spec", title="v2", content="second version",
        source_path="v2.md", attached_to_type="task", attached_to_id=entity_id,
    )
    db_session.add_all([doc1, doc2])
    await db_session.commit()

    result = await db_session.execute(
        select(Document).where(Document.attached_to_id == entity_id)
        .order_by(Document.created_at)
    )
    docs = list(result.scalars().all())
    assert len(docs) == 2
    assert docs[0].title == "v1"
    assert docs[1].title == "v2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-document`
Expected: ImportError — `src.document.models` does not exist.

- [ ] **Step 3: Implement model**

```python
# src/document/models.py
"""SQLAlchemy models for the Document bounded context."""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.database import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    type: Mapped[str] = mapped_column(String(20))  # spec, plan, design, other
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    source_path: Mapped[str] = mapped_column(String(500), default="")
    attached_to_type: Mapped[str] = mapped_column(String(20))  # epic, feature, task
    attached_to_id: Mapped[_uuid.UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test-document`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/document/models.py tests/document/test_models.py
git commit -m "feat(document): add Document SQLAlchemy model"
```

---

### Task 2: Schemas

**Files:**
- Create: `src/document/schemas.py`

- [ ] **Step 1: Create schemas**

```python
# src/document/schemas.py
"""Pydantic schemas for the Document context API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentCreate(BaseModel):
    task_id: UUID  # Convenience alias — maps to attached_to_type="task"
    type: str  # spec, plan, design, other
    title: str
    content: str
    source_path: str = ""


class DocumentCreateGeneric(BaseModel):
    """For attaching to any entity type (epic, feature, task)."""
    attached_to_type: str
    attached_to_id: UUID
    type: str
    title: str
    content: str
    source_path: str = ""


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    title: str
    content: str
    source_path: str
    attached_to_type: str
    attached_to_id: UUID
    created_at: datetime


class DocumentSummary(BaseModel):
    """Lightweight version for task card chips (no content)."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    title: str
    created_at: datetime
```

- [ ] **Step 2: Commit**

```bash
git add src/document/schemas.py
git commit -m "feat(document): add Pydantic schemas"
```

---

### Task 3: Repository

**Files:**
- Create: `src/document/repository.py`

- [ ] **Step 1: Implement repository**

```python
# src/document/repository.py
"""Database queries for the Document bounded context."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.document.models import Document


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        doc_type: str,
        title: str,
        content: str,
        source_path: str,
        attached_to_type: str,
        attached_to_id: UUID,
    ) -> Document:
        doc = Document(
            type=doc_type,
            title=title,
            content=content,
            source_path=source_path,
            attached_to_type=attached_to_type,
            attached_to_id=attached_to_id,
        )
        self._session.add(doc)
        await self._session.commit()
        await self._session.refresh(doc)
        return doc

    async def get(self, document_id: UUID) -> Document | None:
        return await self._session.get(Document, document_id)

    async def list_for_entity(
        self, attached_to_type: str, attached_to_id: UUID
    ) -> list[Document]:
        result = await self._session.execute(
            select(Document)
            .where(
                Document.attached_to_type == attached_to_type,
                Document.attached_to_id == attached_to_id,
            )
            .order_by(Document.created_at)
        )
        return list(result.scalars().all())
```

- [ ] **Step 2: Commit**

```bash
git add src/document/repository.py
git commit -m "feat(document): add repository layer"
```

---

### Task 4: Services

**Files:**
- Create: `src/document/services.py`

- [ ] **Step 1: Implement services**

```python
# src/document/services.py
"""Business logic for the Document bounded context."""

from __future__ import annotations

from uuid import UUID

from src.document.models import Document
from src.document.repository import DocumentRepository
from src.shared.events import Event, EventType, event_bus


class DocumentService:
    def __init__(self, repo: DocumentRepository) -> None:
        self._repo = repo

    async def create_document(
        self,
        doc_type: str,
        title: str,
        content: str,
        source_path: str,
        attached_to_type: str,
        attached_to_id: UUID,
        project_id: UUID | None = None,
    ) -> Document:
        doc = await self._repo.create(
            doc_type=doc_type,
            title=title,
            content=content,
            source_path=source_path,
            attached_to_type=attached_to_type,
            attached_to_id=attached_to_id,
        )

        if project_id is not None:
            await event_bus.publish(Event(
                type=EventType.DOCUMENT_ATTACHED,
                project_id=project_id,
                data={
                    "document_id": str(doc.id),
                    "attached_to_type": attached_to_type,
                    "attached_to_id": str(attached_to_id),
                    "type": doc_type,
                    "title": title,
                },
            ))

        return doc

    async def get_document(self, document_id: UUID) -> Document | None:
        return await self._repo.get(document_id)

    async def list_documents(
        self, attached_to_type: str, attached_to_id: UUID
    ) -> list[Document]:
        return await self._repo.list_for_entity(attached_to_type, attached_to_id)
```

- [ ] **Step 2: Commit**

```bash
git add src/document/services.py
git commit -m "feat(document): add document service with event publishing"
```

---

### Task 5: API Routes + Integration Tests

**Files:**
- Create: `src/document/routes.py`
- Test: `tests/document/test_routes.py`

- [ ] **Step 1: Write route tests**

```python
# tests/document/test_routes.py
import pytest
from httpx import AsyncClient


@pytest.fixture
async def project_with_task(client: AsyncClient) -> dict:
    """Create project + epic + feature + task. Return IDs."""
    p = (await client.post("/api/v1/projects", json={"name": "doc-route-test"})).json()
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


async def test_create_document_for_task(client: AsyncClient, project_with_task: dict):
    h = _auth(project_with_task["api_key"])

    # Register agent first
    reg = (await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/home/user/wt-doc"},
        headers=h,
    )).json()

    resp = await client.post(
        f"/api/v1/agents/{reg['worktree_id']}/documents",
        json={
            "task_id": project_with_task["task_id"],
            "type": "spec",
            "title": "OAuth Spec",
            "content": "# OAuth\n\nFlow description here.",
            "source_path": "docs/oauth.md",
        },
        headers=h,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["type"] == "spec"
    assert data["title"] == "OAuth Spec"
    assert data["attached_to_type"] == "task"


async def test_list_documents_for_task(client: AsyncClient, project_with_task: dict):
    h = _auth(project_with_task["api_key"])
    task_id = project_with_task["task_id"]

    reg = (await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/home/user/wt-doc-list"},
        headers=h,
    )).json()

    # Create two documents
    await client.post(
        f"/api/v1/agents/{reg['worktree_id']}/documents",
        json={"task_id": task_id, "type": "spec", "title": "Spec v1",
              "content": "first"},
        headers=h,
    )
    await client.post(
        f"/api/v1/agents/{reg['worktree_id']}/documents",
        json={"task_id": task_id, "type": "plan", "title": "Plan",
              "content": "second"},
        headers=h,
    )

    resp = await client.get(f"/api/v1/tasks/{task_id}/documents")
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) == 2


async def test_get_document_by_id(client: AsyncClient, project_with_task: dict):
    h = _auth(project_with_task["api_key"])

    reg = (await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/home/user/wt-doc-get"},
        headers=h,
    )).json()

    created = (await client.post(
        f"/api/v1/agents/{reg['worktree_id']}/documents",
        json={"task_id": project_with_task["task_id"], "type": "design",
              "title": "Design Doc", "content": "# Design\n\nDetails."},
        headers=h,
    )).json()

    resp = await client.get(f"/api/v1/documents/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["content"] == "# Design\n\nDetails."


async def test_get_document_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-document`
Expected: Fails — routes don't exist.

- [ ] **Step 3: Implement routes**

```python
# src/document/routes.py
"""FastAPI routes for the Document bounded context."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.document.repository import DocumentRepository
from src.document.schemas import DocumentCreate, DocumentResponse, DocumentSummary
from src.document.services import DocumentService
from src.gateway.auth import require_api_key
from src.shared.database import get_session

router = APIRouter()


def _get_service(session: AsyncSession = Depends(get_session)) -> DocumentService:
    return DocumentService(DocumentRepository(session))


# --- Agent-facing (auth required) ---


@router.post(
    "/agents/{worktree_id}/documents",
    response_model=DocumentResponse,
    status_code=201,
    dependencies=[Depends(require_api_key)],
)
async def create_document(
    worktree_id: UUID,
    body: DocumentCreate,
    request: Request,
    service: DocumentService = Depends(_get_service),
) -> DocumentResponse:
    project = request.state.project
    doc = await service.create_document(
        doc_type=body.type,
        title=body.title,
        content=body.content,
        source_path=body.source_path,
        attached_to_type="task",
        attached_to_id=body.task_id,
        project_id=project.id,
    )
    return DocumentResponse.model_validate(doc)


# --- Dashboard-facing (public) ---


@router.get("/tasks/{task_id}/documents", response_model=list[DocumentSummary])
async def list_task_documents(
    task_id: UUID,
    service: DocumentService = Depends(_get_service),
) -> list[DocumentSummary]:
    docs = await service.list_documents("task", task_id)
    return [DocumentSummary.model_validate(d) for d in docs]


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    service: DocumentService = Depends(_get_service),
) -> DocumentResponse:
    doc = await service.get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse.model_validate(doc)
```

- [ ] **Step 4: Register document router in gateway app.py**

Add to `src/gateway/app.py` after the agent router:

```python
    from src.document.routes import router as document_router
    app.include_router(document_router, prefix="/api/v1")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `make test-document`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/document/routes.py tests/document/test_routes.py src/gateway/app.py
git commit -m "feat(document): add API routes for document creation and retrieval"
```

---

### Task 6: Alembic Migration

- [ ] **Step 1: Generate migration**

```bash
cd /home/sachin/code/cloglog
python -m alembic revision --autogenerate -m "document_context_table"
```

- [ ] **Step 2: Run migration**

```bash
make db-up && make db-migrate
```

- [ ] **Step 3: Commit**

```bash
git add src/alembic/versions/
git commit -m "feat(document): add Alembic migration for documents table"
```

---

### Task 7: Cleanup & Quality Gate

- [ ] **Step 1: Delete placeholder test**

```bash
rm -f tests/document/test_placeholder.py
```

- [ ] **Step 2: Run full quality gate**

Run: `make quality`
Expected: All checks pass.

- [ ] **Step 3: Commit**

```bash
git add -A tests/document/
git commit -m "chore(document): remove placeholder test"
```
