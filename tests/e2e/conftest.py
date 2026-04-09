"""E2E test fixtures.

The root tests/conftest.py provides the `client` fixture with all routers
mounted and X-Dashboard-Key default header. This conftest adds E2E-specific
fixtures like `bare_client` for access control tests.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import src.agent.models  # noqa: F401
import src.board.models  # noqa: F401
import src.document.models  # noqa: F401
from src.shared.database import get_session

_PG_ASYNC_BASE_URL = "postgresql+asyncpg://cloglog:cloglog_dev@localhost:5432"


@pytest.fixture
async def bare_client(test_db_name: str) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client with NO default credentials — tests set headers explicitly."""
    from src.gateway.app import create_app

    test_engine = create_async_engine(f"{_PG_ASYNC_BASE_URL}/{test_db_name}")
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    app = create_app()

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    await test_engine.dispose()
