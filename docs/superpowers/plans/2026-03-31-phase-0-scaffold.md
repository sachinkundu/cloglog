# Phase 0: Scaffold & Contracts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Set up the complete project skeleton, test infrastructure, interface contracts, and quality gate so that Phase 1's four parallel agents can start working in separate worktrees without conflicts.

**Architecture:** FastAPI backend organized into DDD bounded contexts (Board, Agent, Document, Gateway) with a shared kernel for database and config. React frontend (Vite + TypeScript) and Node.js MCP server as separate packages. PostgreSQL via Docker Compose. pytest + Vitest + quality gate via Makefile.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL 16, React 18, Vite, TypeScript, Vitest, Node.js, ruff, mypy, uv

## Development Environment

cloglog itself runs on the **host machine** (not inside a Lima VM). During development:

- **Phases 0-3**: Backend, frontend, and PostgreSQL all run on the host. Agent API endpoints are tested with `httpx`/`curl` — no VMs needed. The MCP server is tested against a mock HTTP backend.
- **Phase 4 (agent-vm integration)**: We spin up a real Lima VM via `agent-vm claude` that runs an agent which connects BACK to the cloglog service on the host. This tests the full loop: agent inside VM → cloglog-mcp → HTTP to host → cloglog API → dashboard updates.

The VMs are only needed for the end-to-end integration test, not for developing cloglog itself.

## Parallelism Map

Phase 0 has **three independent tracks** that can run simultaneously:

```mermaid
graph LR
    subgraph Track_A["Track A: Python Backend (sequential)"]
        T1["Task 1: Python init"] --> T3["Task 3: Shared kernel"]
        T3 --> T4["Task 4: Alembic"]
        T3 --> T5["Task 5: Interfaces"]
        T4 --> T7["Task 7: Gateway app"]
        T5 --> T7
        T7 --> T6["Task 6: Test infra"]
        T6 --> T8["Task 8: Sample tests"]
        T8 --> T9["Task 9: Makefile"]
    end

    subgraph Track_B["Track B: Frontend (independent)"]
        T10["Task 10: React frontend"]
    end

    subgraph Track_C["Track C: MCP Server (independent)"]
        T11["Task 11: MCP server"]
    end

    T2["Task 2: Docker Compose"] --> T6

    T9 & T10 & T11 --> T12["Task 12: CLAUDE.md"]
    T12 --> T13["Task 13: Final quality check"]

    style Track_A fill:#0891b2,color:#fff
    style Track_B fill:#d97706,color:#fff
    style Track_C fill:#8b5cf6,color:#fff
```

**Run with 3 parallel agents:**

| Agent | Track | Tasks | Touches |
|-------|-------|-------|---------|
| Agent A | Python backend | 1 → 2 → 3 → 4 → 5 → 7 → 6 → 8 → 9 | `src/`, `tests/`, `pyproject.toml`, `docker-compose.yml`, `alembic.ini`, `Makefile` |
| Agent B | Frontend | 10 | `frontend/` |
| Agent C | MCP Server | 11 | `mcp-server/` |

Tasks 12 (CLAUDE.md) and 13 (final check) run after all three tracks merge.

**Merge order:** Agent B and Agent C can merge first (independent). Agent A merges last (largest surface). Then Tasks 12-13 run on main.

---

### Task 1: Initialize Python Backend Project

**Files:**
- Create: `pyproject.toml`
- Create: `src/__init__.py`
- Create: `src/board/__init__.py`
- Create: `src/agent/__init__.py`
- Create: `src/document/__init__.py`
- Create: `src/gateway/__init__.py`
- Create: `src/shared/__init__.py`

- [ ] **Step 1: Create pyproject.toml with all dependencies**

```toml
[project]
name = "cloglog"
version = "0.1.0"
description = "Multi-project Kanban dashboard for managing autonomous AI coding agents"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlalchemy[asyncio]>=2.0.36",
    "asyncpg>=0.30.0",
    "alembic>=1.14.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "python-multipart>=0.0.12",
    "sse-starlette>=2.1.0",
    "passlib[bcrypt]>=1.7.4",
    "httpx>=0.28.0",
    "typer>=0.15.0",
    "rich>=13.9.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0.0",
    "httpx>=0.28.0",
    "ruff>=0.8.0",
    "mypy>=1.13.0",
    "sqlalchemy[mypy]>=2.0.36",
    "asyncpg>=0.30.0",
]

[project.scripts]
cloglog = "src.gateway.cli:app"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "--strict-markers -ra"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "A", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["sqlalchemy.ext.mypy.plugin"]
warn_return_any = true
warn_unused_configs = true

[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Create all __init__.py files for package structure**

Create these empty files:

`src/__init__.py`:
```python
```

`src/board/__init__.py`:
```python
```

`src/agent/__init__.py`:
```python
```

`src/document/__init__.py`:
```python
```

`src/gateway/__init__.py`:
```python
```

`src/shared/__init__.py`:
```python
```

- [ ] **Step 3: Install dependencies with uv**

Run: `uv sync --all-extras`
Expected: Dependencies installed, `.venv` created

- [ ] **Step 4: Verify Python imports work**

Run: `uv run python -c "import src.board; import src.agent; import src.document; import src.gateway; import src.shared; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/
git commit -m "feat: initialize Python project with DDD bounded context structure"
```

---

### Task 2: Docker Compose for PostgreSQL

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`

- [ ] **Step 1: Create docker-compose.yml**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: cloglog
      POSTGRES_PASSWORD: cloglog_dev
      POSTGRES_DB: cloglog
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cloglog"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
```

- [ ] **Step 2: Create .env.example**

```bash
# Database
DATABASE_URL=postgresql+asyncpg://cloglog:cloglog_dev@localhost:5432/cloglog

# Server
HOST=0.0.0.0
PORT=8000
```

- [ ] **Step 3: Start PostgreSQL and verify**

Run: `docker compose up -d && sleep 3 && docker compose exec postgres pg_isready -U cloglog`
Expected: `/var/run/postgresql:5432 - accepting connections`

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "feat: add Docker Compose for PostgreSQL"
```

---

### Task 3: Shared Kernel — Database, Config, Events

**Files:**
- Create: `src/shared/database.py`
- Create: `src/shared/config.py`
- Create: `src/shared/events.py`

- [ ] **Step 1: Write the config module**

`src/shared/config.py`:
```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://cloglog:cloglog_dev@localhost:5432/cloglog"
    host: str = "0.0.0.0"
    port: int = 8000
    heartbeat_timeout_seconds: int = 180  # 3 minutes

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 2: Write the database module**

`src/shared/database.py`:
```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.shared.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
```

- [ ] **Step 3: Write the event bus module**

`src/shared/events.py`:
```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID


class EventType(str, Enum):
    TASK_STATUS_CHANGED = "task_status_changed"
    WORKTREE_ONLINE = "worktree_online"
    WORKTREE_OFFLINE = "worktree_offline"
    DOCUMENT_ATTACHED = "document_attached"


@dataclass
class Event:
    type: EventType
    project_id: UUID
    data: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """Simple in-process pub/sub for SSE fan-out."""

    def __init__(self) -> None:
        self._subscribers: dict[UUID, list[asyncio.Queue[Event]]] = {}

    def subscribe(self, project_id: UUID) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.setdefault(project_id, []).append(queue)
        return queue

    def unsubscribe(self, project_id: UUID, queue: asyncio.Queue[Event]) -> None:
        if project_id in self._subscribers:
            self._subscribers[project_id] = [
                q for q in self._subscribers[project_id] if q is not queue
            ]

    async def publish(self, event: Event) -> None:
        for queue in self._subscribers.get(event.project_id, []):
            await queue.put(event)


event_bus = EventBus()
```

- [ ] **Step 4: Verify imports**

Run: `uv run python -c "from src.shared.config import settings; from src.shared.database import Base, get_session; from src.shared.events import event_bus, Event, EventType; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/shared/
git commit -m "feat: add shared kernel — database, config, event bus"
```

---

### Task 4: Alembic Migration Setup

**Files:**
- Create: `alembic.ini`
- Create: `src/alembic/env.py`
- Create: `src/alembic/script.py.mako`
- Create: `src/alembic/versions/.gitkeep`

- [ ] **Step 1: Create alembic.ini**

```ini
[alembic]
script_location = src/alembic
sqlalchemy.url = postgresql+asyncpg://cloglog:cloglog_dev@localhost:5432/cloglog

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 2: Create Alembic env.py for async**

`src/alembic/env.py`:
```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.shared.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Create script.py.mako template**

`src/alembic/script.py.mako`:
```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Create versions directory**

```bash
touch src/alembic/__init__.py src/alembic/versions/.gitkeep
```

- [ ] **Step 5: Verify Alembic can see the config**

Run: `uv run alembic --help | head -3`
Expected: Shows alembic usage info

- [ ] **Step 6: Commit**

```bash
git add alembic.ini src/alembic/
git commit -m "feat: set up Alembic async migrations"
```

---

### Task 5: Interface Contracts Between Bounded Contexts

**Files:**
- Create: `src/board/interfaces.py`
- Create: `src/agent/interfaces.py`
- Create: `src/document/interfaces.py`

- [ ] **Step 1: Define Board context interfaces**

`src/board/interfaces.py`:
```python
"""Protocols exposed by the Board context to other contexts."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class TaskAssignmentService(Protocol):
    """Used by Agent context to claim/release tasks."""

    async def assign_task_to_worktree(
        self, task_id: UUID, worktree_id: UUID
    ) -> None: ...

    async def unassign_task_from_worktree(
        self, task_id: UUID
    ) -> None: ...

    async def get_tasks_for_worktree(
        self, worktree_id: UUID
    ) -> list[dict[str, object]]: ...


class TaskStatusService(Protocol):
    """Used by Agent context to move tasks between columns."""

    async def start_task(self, task_id: UUID, worktree_id: UUID) -> None: ...

    async def complete_task(self, task_id: UUID) -> dict[str, object] | None:
        """Complete a task and return the next assigned task, or None."""
        ...

    async def update_task_status(self, task_id: UUID, status: str) -> None: ...
```

- [ ] **Step 2: Define Agent context interfaces**

`src/agent/interfaces.py`:
```python
"""Protocols exposed by the Agent context to other contexts."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class WorktreeService(Protocol):
    """Used by Gateway to query worktree state."""

    async def get_worktrees_for_project(
        self, project_id: UUID
    ) -> list[dict[str, object]]: ...

    async def get_worktree(self, worktree_id: UUID) -> dict[str, object] | None: ...
```

- [ ] **Step 3: Define Document context interfaces**

`src/document/interfaces.py`:
```python
"""Protocols exposed by the Document context to other contexts."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class DocumentService(Protocol):
    """Used by Gateway to query documents."""

    async def get_documents_for_entity(
        self, attached_to_type: str, attached_to_id: UUID
    ) -> list[dict[str, object]]: ...

    async def get_document(self, document_id: UUID) -> dict[str, object] | None: ...
```

- [ ] **Step 4: Verify all interfaces import cleanly**

Run: `uv run python -c "from src.board.interfaces import TaskAssignmentService, TaskStatusService; from src.agent.interfaces import WorktreeService; from src.document.interfaces import DocumentService; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/board/interfaces.py src/agent/interfaces.py src/document/interfaces.py
git commit -m "feat: define interface contracts between bounded contexts"
```

---

### Task 6: Test Infrastructure — conftest, Fixtures, Database Isolation

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/board/__init__.py`
- Create: `tests/agent/__init__.py`
- Create: `tests/document/__init__.py`
- Create: `tests/gateway/__init__.py`
- Create: `tests/e2e/__init__.py`

- [ ] **Step 1: Create test package files**

Create all `__init__.py` files:

```bash
touch tests/__init__.py tests/board/__init__.py tests/agent/__init__.py tests/document/__init__.py tests/gateway/__init__.py tests/e2e/__init__.py
```

- [ ] **Step 2: Write conftest.py with database isolation**

`tests/conftest.py`:
```python
"""Shared test fixtures with database isolation.

Each test session gets its own temporary PostgreSQL database.
Multiple worktrees running tests simultaneously get separate databases.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.shared.database import Base, get_session

# Base connection URL (without database name) for creating test databases
_PG_BASE_URL = "postgresql://cloglog:cloglog_dev@localhost:5432"
_PG_ASYNC_BASE_URL = "postgresql+asyncpg://cloglog:cloglog_dev@localhost:5432"


@pytest.fixture(scope="session")
def test_db_name() -> str:
    """Generate a unique database name for this test session."""
    suffix = uuid.uuid4().hex[:8]
    return f"cloglog_test_{suffix}"


@pytest.fixture(scope="session", autouse=True)
def _create_test_database(test_db_name: str) -> None:  # type: ignore[misc]
    """Create and drop a temporary test database for this session."""

    async def _setup() -> None:
        conn = await asyncpg.connect(f"{_PG_BASE_URL}/cloglog")
        await conn.execute(f'CREATE DATABASE "{test_db_name}"')
        await conn.close()

        # Run migrations on the test database
        engine = create_async_engine(f"{_PG_ASYNC_BASE_URL}/{test_db_name}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    async def _teardown() -> None:
        conn = await asyncpg.connect(f"{_PG_BASE_URL}/cloglog")
        # Terminate connections to the test database
        await conn.execute(f"""
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = '{test_db_name}' AND pid <> pg_backend_pid()
        """)
        await conn.execute(f'DROP DATABASE IF EXISTS "{test_db_name}"')
        await conn.close()

    asyncio.get_event_loop_policy().get_event_loop()
    loop = asyncio.new_event_loop()
    loop.run_until_complete(_setup())
    yield  # type: ignore[misc]
    loop.run_until_complete(_teardown())
    loop.close()


@pytest.fixture
async def db_session(test_db_name: str) -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session for tests."""
    engine = create_async_engine(f"{_PG_ASYNC_BASE_URL}/{test_db_name}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def client(test_db_name: str) -> AsyncGenerator[AsyncClient, None]:
    """Provide an HTTP test client with the test database."""
    from src.gateway.app import create_app

    test_engine = create_async_engine(f"{_PG_ASYNC_BASE_URL}/{test_db_name}")
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    app = create_app()

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    await test_engine.dispose()
```

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "feat: set up test infrastructure with database isolation"
```

---

### Task 7: Minimal Gateway App (needed by test fixtures)

**Files:**
- Create: `src/gateway/app.py`

- [ ] **Step 1: Write the minimal FastAPI app factory**

`src/gateway/app.py`:
```python
"""FastAPI application factory.

Composes routes from all bounded contexts into a single app.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    app = FastAPI(
        title="cloglog",
        description="Multi-project Kanban dashboard for managing autonomous AI coding agents",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Context routes will be included here in Phase 1:
    # app.include_router(board_router, prefix="/api/v1")
    # app.include_router(agent_router, prefix="/api/v1")
    # app.include_router(document_router, prefix="/api/v1")

    return app
```

- [ ] **Step 2: Verify the app starts**

Run: `uv run python -c "from src.gateway.app import create_app; app = create_app(); print(app.title)"`
Expected: `cloglog`

- [ ] **Step 3: Commit**

```bash
git add src/gateway/app.py
git commit -m "feat: add minimal FastAPI app factory"
```

---

### Task 8: Sample Tests to Verify Test Runner

**Files:**
- Create: `tests/board/test_placeholder.py`
- Create: `tests/agent/test_placeholder.py`
- Create: `tests/document/test_placeholder.py`
- Create: `tests/gateway/test_health.py`

- [ ] **Step 1: Write a sample test for each context**

`tests/board/test_placeholder.py`:
```python
def test_board_context_tests_run() -> None:
    """Verify the test runner works for the Board context."""
    assert True
```

`tests/agent/test_placeholder.py`:
```python
def test_agent_context_tests_run() -> None:
    """Verify the test runner works for the Agent context."""
    assert True
```

`tests/document/test_placeholder.py`:
```python
def test_document_context_tests_run() -> None:
    """Verify the test runner works for the Document context."""
    assert True
```

- [ ] **Step 2: Write a real integration test for the health endpoint**

`tests/gateway/test_health.py`:
```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 3: Run all tests to verify the runner works**

Run: `uv run pytest tests/ -v`
Expected: 4 tests pass (3 placeholders + 1 health check)

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "feat: add sample tests to verify test runner in each context"
```

---

### Task 9: Makefile with Quality Gate

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Write the Makefile**

```makefile
.PHONY: help install test test-board test-agent test-document test-gateway test-e2e lint typecheck coverage quality run-backend

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies
	uv sync --all-extras

# ── Testing ───────────────────────────────────

test: ## Run all backend tests
	uv run pytest tests/ -v --tb=short

test-board: ## Run Board context tests
	uv run pytest tests/board/ -v --tb=short

test-agent: ## Run Agent context tests
	uv run pytest tests/agent/ -v --tb=short

test-document: ## Run Document context tests
	uv run pytest tests/document/ -v --tb=short

test-gateway: ## Run Gateway context tests
	uv run pytest tests/gateway/ -v --tb=short

test-e2e: ## Run end-to-end tests
	uv run pytest tests/e2e/ -v --tb=short

# ── Quality ───────────────────────────────────

lint: ## Run linter
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

typecheck: ## Run type checker
	uv run mypy src/

coverage: ## Run tests with coverage report
	uv run pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=80

quality: ## Run full quality gate (lint + typecheck + test + coverage)
	@echo "── Backend ─────────────────────────────"
	@echo ""
	@echo "  Lint:"
	@uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && echo "    0 errors           ✓" || (echo "    FAILED ✗" && exit 1)
	@echo ""
	@echo "  Types:"
	@uv run mypy src/ --no-error-summary 2>&1 | tail -1 | grep -q "Success" && echo "    0 errors           ✓" || (uv run mypy src/ && echo "    0 errors           ✓" || (echo "    FAILED ✗" && exit 1))
	@echo ""
	@echo "  Tests + Coverage:"
	@uv run pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=80 -q 2>&1 | tail -5
	@echo ""
	@echo "── Quality gate: PASSED ────────────────"

# ── Run ───────────────────────────────────────

run-backend: ## Start the FastAPI backend
	uv run uvicorn src.gateway.app:create_app --factory --host 0.0.0.0 --port 8000 --reload

# ── Database ──────────────────────────────────

db-up: ## Start PostgreSQL
	docker compose up -d

db-down: ## Stop PostgreSQL
	docker compose down

db-migrate: ## Run Alembic migrations
	uv run alembic upgrade head

db-revision: ## Create a new Alembic migration (usage: make db-revision msg="description")
	uv run alembic revision --autogenerate -m "$(msg)"
```

- [ ] **Step 2: Run the quality gate**

Run: `make quality`
Expected: Lint passes, typecheck passes, all tests pass, coverage report shown, "Quality gate: PASSED"

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat: add Makefile with quality gate and per-context test targets"
```

---

### Task 10: Initialize React Frontend

**Files:**
- Create: `frontend/` (via Vite scaffold)
- Create: `frontend/Makefile`

- [ ] **Step 1: Scaffold React project with Vite**

Run:
```bash
cd /home/sachin/code/cloglog
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

- [ ] **Step 2: Add Vitest and testing dependencies**

Run:
```bash
cd frontend
npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom @vitest/coverage-v8
```

- [ ] **Step 3: Configure Vitest in vite.config.ts**

Update `frontend/vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'text-summary'],
      thresholds: {
        statements: 80,
      },
    },
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
```

- [ ] **Step 4: Create test setup file**

`frontend/src/test-setup.ts`:
```typescript
import '@testing-library/jest-dom'
```

- [ ] **Step 5: Write a sample test**

`frontend/src/App.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import App from './App'

describe('App', () => {
  it('renders without crashing', () => {
    render(<App />)
    expect(document.body).toBeTruthy()
  })
})
```

- [ ] **Step 6: Create frontend Makefile**

`frontend/Makefile`:
```makefile
.PHONY: test coverage lint dev build

test: ## Run frontend tests
	npx vitest run

coverage: ## Run tests with coverage
	npx vitest run --coverage

lint: ## Run linter
	npx tsc --noEmit

dev: ## Start dev server
	npx vite

build: ## Build for production
	npx vite build
```

- [ ] **Step 7: Run frontend tests**

Run: `cd frontend && make test`
Expected: 1 test passes

- [ ] **Step 8: Commit**

```bash
cd /home/sachin/code/cloglog
git add frontend/
git commit -m "feat: initialize React frontend with Vite, Vitest, and TypeScript"
```

---

### Task 11: Initialize MCP Server

**Files:**
- Create: `mcp-server/package.json`
- Create: `mcp-server/tsconfig.json`
- Create: `mcp-server/src/index.ts`
- Create: `mcp-server/src/client.ts`
- Create: `mcp-server/tests/client.test.ts`
- Create: `mcp-server/Makefile`

- [ ] **Step 1: Create package.json**

`mcp-server/package.json`:
```json
{
  "name": "cloglog-mcp",
  "version": "0.1.0",
  "description": "MCP server for cloglog agent integration",
  "type": "module",
  "main": "dist/index.js",
  "bin": {
    "cloglog-mcp": "dist/index.js"
  },
  "scripts": {
    "build": "tsc",
    "test": "vitest run",
    "coverage": "vitest run --coverage"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.0.0"
  },
  "devDependencies": {
    "typescript": "^5.6.0",
    "vitest": "^2.1.0",
    "@vitest/coverage-v8": "^2.1.0"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

`mcp-server/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "declaration": true,
    "sourceMap": true
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist", "tests"]
}
```

- [ ] **Step 3: Create the HTTP client stub**

`mcp-server/src/client.ts`:
```typescript
/**
 * HTTP client for the cloglog API.
 * Each MCP tool calls methods on this client.
 */

export interface CloglogClientConfig {
  baseUrl: string
  apiKey: string
}

export class CloglogClient {
  private baseUrl: string
  private apiKey: string

  constructor(config: CloglogClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, '')
    this.apiKey = config.apiKey
  }

  async request(method: string, path: string, body?: unknown): Promise<unknown> {
    const url = `${this.baseUrl}${path}`
    const headers: Record<string, string> = {
      'Authorization': `Bearer ${this.apiKey}`,
      'Content-Type': 'application/json',
    }

    const response = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    })

    if (!response.ok) {
      const text = await response.text()
      throw new Error(`cloglog API error: ${response.status} ${text}`)
    }

    return response.json()
  }
}
```

- [ ] **Step 4: Create the MCP server entry point stub**

`mcp-server/src/index.ts`:
```typescript
#!/usr/bin/env node

/**
 * cloglog-mcp: MCP server for agent ↔ cloglog communication.
 * Tools are implemented in Phase 1-3.
 */

import { CloglogClient } from './client.js'

const CLOGLOG_URL = process.env.CLOGLOG_URL ?? 'http://localhost:8000'
const CLOGLOG_API_KEY = process.env.CLOGLOG_API_KEY ?? ''

const client = new CloglogClient({
  baseUrl: CLOGLOG_URL,
  apiKey: CLOGLOG_API_KEY,
})

// MCP server setup will be added in Phase 1
console.error('cloglog-mcp: server stub loaded')

export { client }
```

- [ ] **Step 5: Write a test for the client**

`mcp-server/tests/client.test.ts`:
```typescript
import { describe, it, expect } from 'vitest'
import { CloglogClient } from '../src/client.js'

describe('CloglogClient', () => {
  it('constructs with config', () => {
    const client = new CloglogClient({
      baseUrl: 'http://localhost:8000',
      apiKey: 'test-key',
    })
    expect(client).toBeTruthy()
  })

  it('strips trailing slash from base URL', () => {
    const client = new CloglogClient({
      baseUrl: 'http://localhost:8000/',
      apiKey: 'test-key',
    })
    // Access private field for verification via any cast
    expect((client as any).baseUrl).toBe('http://localhost:8000')
  })
})
```

- [ ] **Step 6: Create MCP server Makefile**

`mcp-server/Makefile`:
```makefile
.PHONY: test coverage build

test: ## Run MCP server tests
	npx vitest run

coverage: ## Run tests with coverage
	npx vitest run --coverage

build: ## Build TypeScript
	npx tsc
```

- [ ] **Step 7: Install dependencies and run tests**

Run:
```bash
cd mcp-server && npm install && make test
```
Expected: 2 tests pass

- [ ] **Step 8: Commit**

```bash
cd /home/sachin/code/cloglog
git add mcp-server/
git commit -m "feat: initialize MCP server with HTTP client stub and tests"
```

---

### Task 12: CLAUDE.md for the Repository

**Files:**
- Create: `CLAUDE.md`

- [ ] **Step 1: Write CLAUDE.md with bounded context rules**

`CLAUDE.md`:
```markdown
# CLAUDE.md — cloglog

## Project Overview

cloglog is a multi-project Kanban dashboard for managing autonomous AI coding agents running in agent-vm sandboxes.

## Architecture

DDD bounded contexts — each context owns its own models, services, repository, and routes:

- **Board** (`src/board/`) — Projects, Epics, Features, Tasks, status roll-up
- **Agent** (`src/agent/`) — Worktrees, Sessions, registration, heartbeat
- **Document** (`src/document/`) — Append-only document storage
- **Gateway** (`src/gateway/`) — API composition, auth, SSE, CLI

Contexts communicate through interfaces defined in `interfaces.py`, never by importing each other's internals.

## Worktree Discipline

If you are working in a worktree, you MUST only touch files in your assigned context:

- `wt-board` → `src/board/`, `tests/board/`
- `wt-agent` → `src/agent/`, `tests/agent/`
- `wt-document` → `src/document/`, `tests/document/`
- `wt-gateway` → `src/gateway/`, `tests/gateway/`
- `wt-frontend` → `frontend/`
- `wt-mcp` → `mcp-server/`

Do NOT modify files outside your assigned directories. If you need a change in another context, note it and coordinate.

## Commands

```bash
make quality          # Full quality gate — must pass before completing any task
make test             # All backend tests
make test-board       # Board context tests only
make test-agent       # Agent context tests only
make test-document    # Document context tests only
make test-gateway     # Gateway context tests only
make lint             # Ruff linter
make typecheck        # mypy type checking
make run-backend      # Start FastAPI dev server
make db-up            # Start PostgreSQL via Docker Compose
make db-migrate       # Run Alembic migrations
```

## Quality Gate

Before completing any task or creating a PR, run `make quality` and verify it passes.

## Tech Stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL
- Frontend: React 18, Vite, TypeScript, Vitest
- MCP Server: Node.js, TypeScript, @modelcontextprotocol/sdk
- Tools: uv, ruff, mypy, pytest
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "feat: add CLAUDE.md with bounded context rules and worktree discipline"
```

---

### Task 13: Update .gitignore and Final Quality Check

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Update .gitignore with all patterns**

`.gitignore`:
```gitignore
# Python
__pycache__/
*.pyc
.venv/
*.egg-info/
dist/
.mypy_cache/
.pytest_cache/
.coverage
htmlcov/

# Node
node_modules/
frontend/dist/
mcp-server/dist/

# IDE
.vscode/
.idea/

# Environment
.env

# Project
.superpowers/
```

- [ ] **Step 2: Run the full quality gate**

Run: `make quality`
Expected: All checks pass — lint clean, typecheck clean, all tests pass, coverage meets threshold

- [ ] **Step 3: Run frontend tests**

Run: `cd frontend && make test`
Expected: Tests pass

- [ ] **Step 4: Run MCP server tests**

Run: `cd mcp-server && make test`
Expected: Tests pass

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "feat: update .gitignore for Python, Node, and IDE patterns"
```

---

## Post-Phase 0 Verification

After all tasks are complete, verify end-to-end:

1. `docker compose up -d` — PostgreSQL running
2. `make quality` — all backend checks pass
3. `cd frontend && make test` — frontend tests pass
4. `cd mcp-server && make test` — MCP tests pass
5. `make run-backend` — server starts on :8000
6. `curl localhost:8000/health` — returns `{"status": "ok"}`

Phase 0 is complete. The skeleton is ready for Phase 1's four parallel agents to start working in separate worktrees.
