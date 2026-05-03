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
        print("    SLUG=$(grep '^project:' .cloglog/config.yaml | head -n1 \\")
        print("           | sed 's/^project:[[:space:]]*//; s/[[:space:]]*#.*$//' \\")
        print("           | tr -d '\"'\"'\"')")
        print(
            "    [[ \"$SLUG\" =~ ^[A-Za-z0-9._-]+$ ]] || "
            '{ echo "ERROR: project: in .cloglog/config.yaml is not slug-safe"; exit 1; }'
        )
        print(f"    printf 'CLOGLOG_API_KEY={new_key}\\n' > ~/.cloglog/credentials.d/\"$SLUG\"")
        print('    chmod 600 ~/.cloglog/credentials.d/"$SLUG"')
        print()
        print("  The slug MUST come from the host's own .cloglog/config.yaml — backend")
        print("  project names are unconstrained free-form strings (e.g. 'My Project'),")
        print("  but the resolver demands [A-Za-z0-9._-]+. Init slugifies the name when")
        print("  it persists `project:`, so different checkouts of the same project may")
        print("  carry slightly different slugs; reading config on each host is the only")
        print("  way to be sure you write the file the resolver will actually read.")
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
