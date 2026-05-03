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

        # Slug used by the T-382 per-project resolver. Matches the same
        # validator the resolver applies (`[A-Za-z0-9._-]+`); leave the
        # actual slug derivation to the operator on their host since the
        # config field they use is per-checkout.
        slug = project.name

        print(f"Project: {project.name} ({project.id})")
        print(f"New API key: {new_key}")
        print()
        print("Update the credentials file the resolver actually reads for THIS")
        print("project on every host that runs an MCP server (dev workstation, prod,")
        print("alt-checkouts). Pick the right destination — the wrong one clobbers")
        print("another project's key on a multi-project host:")
        print()
        print("  Single-project host (only this project on the box):")
        print(f"    printf 'CLOGLOG_API_KEY={new_key}\\n' > ~/.cloglog/credentials")
        print("    chmod 600 ~/.cloglog/credentials")
        print()
        print("  Multi-project host (this project shares the box with others):")
        print(f"    printf 'CLOGLOG_API_KEY={new_key}\\n' > ~/.cloglog/credentials.d/{slug}")
        print(f"    chmod 600 ~/.cloglog/credentials.d/{slug}")
        print()
        print(f"  (The slug above mirrors `project: {slug}` in this repo's")
        print("   .cloglog/config.yaml. If your config uses a different slug, write")
        print("   the file under THAT name, not this one.)")
        print()
        print("Or export in the launcher's environment (one-shot override):")
        print(f"  export CLOGLOG_API_KEY={new_key}")
        print()
        print("Restart Claude Code on each host so the MCP server picks up the new")
        print("key. T-382 fail-loud invariant: a stale credentials.d/<slug> file")
        print("will keep the OLD key in use until you update it. See")
        print("docs/setup-credentials.md.")


async def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        await rotate(name)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
