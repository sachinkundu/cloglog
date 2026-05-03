import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import src.agent.models  # noqa: F401 — register models for autogenerate
import src.board.models  # noqa: F401 — register models for autogenerate
import src.document.models  # noqa: F401 — register models for autogenerate
import src.review.models  # noqa: F401 — register models for autogenerate
from alembic import context
from src.shared.config import settings
from src.shared.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# T-388: DATABASE_URL is required. alembic.ini no longer carries a default
# URL. `Settings` loads `.env` and raises a clear ValidationError when
# `DATABASE_URL` is unset, so alembic refuses to run rather than silently
# migrating the prod `cloglog` DB. Pin: tests/test_database_url_required.py.
config.set_main_option("sqlalchemy.url", settings.database_url)

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
