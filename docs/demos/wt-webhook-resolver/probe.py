"""T-254 demo probe — exercises the webhook resolver against a seeded DB.

Run modes (argv[1]):

    seed     — seed the worktree's isolated DB with a project and three online
               worktrees that carry an empty ``branch_name`` (reproduces the
               crash condition exactly).
    resolve  — feed an ``issue_comment`` WebhookEvent with empty ``head_branch``
               to ``AgentNotifierConsumer._resolve_agent`` against the seeded
               DB. Prints ``OK: no agent resolved`` on the intended path; dies
               with ``FAIL: MultipleResultsFound`` on regression.
    reconnect — register a worktree with an explicit branch_name, reconnect
               with an empty branch_name, and assert the stored name is NOT
               overwritten. Pins ``upsert_worktree``'s defensive guard that
               protects the populated row from a transient empty value.
    repo     — call ``AgentRepository.get_worktree_by_branch`` with an empty
               string against the seeded DB. Prints ``OK: None`` on the guard
               path; dies with ``FAIL: MultipleResultsFound`` on regression.

All output is deterministic (no timings/PIDs/UUIDs leak), so ``showboat
verify`` is byte-stable across runs.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

from sqlalchemy import delete
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.agent.models import Worktree
from src.agent.repository import AgentRepository
from src.agent.services import AgentService
from src.board.models import Project
from src.board.repository import BoardRepository
from src.gateway.webhook_consumers import AgentNotifierConsumer
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType

DB_URL = os.environ["DATABASE_URL"]
PROJECT_NAME = "t254-probe-project"
REPO_FULL = "sachinkundu/t254-probe"


def _engine() -> object:
    return create_async_engine(DB_URL)


async def _seed() -> None:
    """Reset and reseed the probe project + three empty-branch worktrees."""
    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        existing = (
            await session.execute(
                Project.__table__.select().where(Project.name == PROJECT_NAME)
            )
        ).first()
        if existing is not None:
            await session.execute(
                delete(Worktree).where(Worktree.project_id == existing.id)
            )
            await session.execute(delete(Project).where(Project.id == existing.id))
            await session.commit()

        project = Project(
            name=PROJECT_NAME,
            description="T-254 probe",
            repo_url=f"https://github.com/{REPO_FULL}",
        )
        session.add(project)
        await session.flush()

        for i in range(3):
            session.add(
                Worktree(
                    project_id=project.id,
                    worktree_path=f"/tmp/t254-probe-{i}",
                    branch_name="",
                    status="online",
                )
            )
        await session.commit()
    await engine.dispose()
    print("OK: seeded 3 empty-branch online worktrees")


async def _resolve() -> None:
    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        event = WebhookEvent(
            type=WebhookEventType.ISSUE_COMMENT,
            delivery_id="t254-probe",
            repo_full_name=REPO_FULL,
            pr_number=1,
            pr_url="https://example.invalid/pr/1",
            head_branch="",  # issue_comment arrives with empty head_branch
            base_branch="main",
            sender="demo",
            raw={"comment": {"body": "LGTM"}},
        )
        consumer = AgentNotifierConsumer()
        try:
            result = await consumer._resolve_agent(event, session)
        except MultipleResultsFound:
            print("FAIL: MultipleResultsFound raised (T-254 regression)")
            sys.exit(1)
    await engine.dispose()
    if result is None:
        print("OK: no agent resolved")
    else:
        print(f"FAIL: resolver matched {result} — expected None")
        sys.exit(1)


async def _repo() -> None:
    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        proj = (
            await session.execute(
                Project.__table__.select().where(Project.name == PROJECT_NAME)
            )
        ).first()
        if proj is None:
            print("FAIL: probe project not seeded — run 'seed' first")
            sys.exit(1)
        repo = AgentRepository(session)
        try:
            found = await repo.get_worktree_by_branch(proj.id, "")
        except MultipleResultsFound:
            print("FAIL: MultipleResultsFound raised (T-254 regression)")
            sys.exit(1)
    await engine.dispose()
    if found is None:
        print("OK: None")
    else:
        print(f"FAIL: repo matched a row — expected None")
        sys.exit(1)


async def _reconnect() -> None:
    """Seed a row with branch_name='wt-preserve', then re-register with
    branch_name=''. Assert the row still carries 'wt-preserve'."""
    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        suffix = uuid.uuid4().hex[:6]
        project = Project(
            name=f"t254-reconnect-{suffix}",
            description="T-254 reconnect guard",
            repo_url=f"https://github.com/test/reconnect-{suffix}",
        )
        session.add(project)
        await session.flush()
        service = AgentService(AgentRepository(session), BoardRepository(session))

        path = f"/vm-only/t254-reconnect-{suffix}"
        r1 = await service.register(project.id, path, "wt-preserve")
        r2 = await service.register(project.id, path, "")
        assert r1["worktree_id"] == r2["worktree_id"]
        wt = await AgentRepository(session).get_worktree(r2["worktree_id"])  # type: ignore[arg-type]
    await engine.dispose()
    if wt is not None and wt.branch_name == "wt-preserve":
        print("OK: reconnect preserved branch_name")
    else:
        print(f"FAIL: branch_name={wt.branch_name if wt else None!r} (expected 'wt-preserve')")
        sys.exit(1)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "seed":
        asyncio.run(_seed())
    elif mode == "resolve":
        asyncio.run(_resolve())
    elif mode == "repo":
        asyncio.run(_repo())
    elif mode == "reconnect":
        asyncio.run(_reconnect())
    else:
        print(f"FAIL: unknown mode {mode!r}")
        sys.exit(2)


if __name__ == "__main__":
    main()
