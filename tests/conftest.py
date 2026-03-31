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
