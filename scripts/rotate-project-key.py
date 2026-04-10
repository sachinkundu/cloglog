#!/usr/bin/env python3
"""Rotate the project API key and print the new plaintext key.

Usage:
    uv run python scripts/rotate-project-key.py [project-name]

If no project name is given, rotates the key for the first (only) project.
"""

import asyncio
import hashlib
import secrets
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.database import async_session_factory, engine
from src.board.models import Project


async def rotate(project_name: str | None) -> None:
    async with async_session_factory() as session:
        if project_name:
            result = await session.execute(
                select(Project).where(Project.name == project_name)
            )
            project = result.scalar_one_or_none()
            if not project:
                print(f"Error: no project named '{project_name}'", file=sys.stderr)
                sys.exit(1)
        else:
            result = await session.execute(select(Project))
            projects = list(result.scalars().all())
            if len(projects) == 0:
                print("Error: no projects found", file=sys.stderr)
                sys.exit(1)
            if len(projects) > 1:
                print("Error: multiple projects found, specify a name:", file=sys.stderr)
                for p in projects:
                    print(f"  - {p.name}", file=sys.stderr)
                sys.exit(1)
            project = projects[0]

        new_key = secrets.token_hex(32)
        project.api_key_hash = hashlib.sha256(new_key.encode()).hexdigest()
        await session.commit()

        print(f"Project: {project.name} ({project.id})")
        print(f"New API key: {new_key}")
        print()
        print("Set this in your MCP server config:")
        print(f'  CLOGLOG_API_KEY={new_key}')


async def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        await rotate(name)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
