"""E2E test fixtures with all bounded context routers mounted.

Unlike context-specific tests, e2e tests exercise the full API surface
with all routers (board, agent, document, gateway) available.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import all models so Base.metadata.create_all creates all tables
import src.agent.models  # noqa: F401
import src.board.models  # noqa: F401
import src.document.models  # noqa: F401
from src.shared.database import get_session

_PG_ASYNC_BASE_URL = "postgresql+asyncpg://cloglog:cloglog_dev@localhost:5432"


@pytest.fixture
async def client(test_db_name: str) -> AsyncGenerator[AsyncClient, None]:
    """HTTP test client with ALL context routers mounted for e2e testing."""
    from src.agent.routes import router as agent_router
    from src.gateway.app import create_app

    test_engine = create_async_engine(f"{_PG_ASYNC_BASE_URL}/{test_db_name}")
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    app = create_app()

    # Mount agent routes (not yet enabled in gateway app.py)
    app.include_router(agent_router, prefix="/api/v1")

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Dashboard-Key": "cloglog-dashboard-dev"},
    ) as ac:
        yield ac

    await test_engine.dispose()
