"""Integration tests for BoardService.get_unresolved_blockers (F-11)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Epic, Feature, FeatureDependency, Project, Task
from src.board.repository import BoardRepository
from src.board.services import BoardService


async def _make_project(db: AsyncSession) -> Project:
    p = Project(name=f"blocker-{uuid.uuid4().hex[:8]}", description="")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _make_feature(db: AsyncSession, epic: Epic, title: str, number: int) -> Feature:
    f = Feature(epic_id=epic.id, title=title, position=number, number=number)
    db.add(f)
    await db.commit()
    await db.refresh(f)
    return f


async def _make_task(
    db: AsyncSession,
    feature: Feature,
    number: int,
    status: str = "backlog",
    pr_url: str | None = None,
    artifact_path: str | None = None,
    task_type: str = "task",
    title: str = "t",
) -> Task:
    t = Task(
        feature_id=feature.id,
        title=title,
        description="",
        priority="normal",
        position=number,
        status=status,
        task_type=task_type,
        pr_url=pr_url,
        artifact_path=artifact_path,
        number=number,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


class TestGetUnresolvedBlockers:
    async def test_no_dependencies_returns_empty(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        epic = Epic(project_id=project.id, title="E", position=0, color="#000")
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)
        feature = await _make_feature(db_session, epic, "F-A", 1)
        task = await _make_task(db_session, feature, 1)

        svc = BoardService(BoardRepository(db_session))
        blockers = await svc.get_unresolved_blockers(task.id)
        assert blockers == []

    async def test_feature_blocker_on_incomplete_upstream_task(
        self, db_session: AsyncSession
    ) -> None:
        project = await _make_project(db_session)
        epic = Epic(project_id=project.id, title="E", position=0, color="#000")
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        f_up = await _make_feature(db_session, epic, "Upstream", 1)
        f_down = await _make_feature(db_session, epic, "Downstream", 2)
        await _make_task(db_session, f_up, 10, status="backlog")
        downstream_task = await _make_task(db_session, f_down, 20)

        # f_down depends on f_up
        db_session.add(FeatureDependency(feature_id=f_down.id, depends_on_id=f_up.id))
        await db_session.commit()

        svc = BoardService(BoardRepository(db_session))
        blockers = await svc.get_unresolved_blockers(downstream_task.id)
        assert len(blockers) == 1
        b = blockers[0]
        assert b["kind"] == "feature"
        assert b["feature_id"] == str(f_up.id)
        assert b["feature_number"] == 1
        assert b["feature_title"] == "Upstream"
        assert b["incomplete_task_numbers"] == [10]

    async def test_upstream_done_resolves(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        epic = Epic(project_id=project.id, title="E", position=0, color="#000")
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        f_up = await _make_feature(db_session, epic, "Upstream", 1)
        f_down = await _make_feature(db_session, epic, "Downstream", 2)
        await _make_task(db_session, f_up, 10, status="done")
        downstream_task = await _make_task(db_session, f_down, 20)
        db_session.add(FeatureDependency(feature_id=f_down.id, depends_on_id=f_up.id))
        await db_session.commit()

        svc = BoardService(BoardRepository(db_session))
        assert await svc.get_unresolved_blockers(downstream_task.id) == []

    async def test_upstream_review_with_pr_url_resolves(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        epic = Epic(project_id=project.id, title="E", position=0, color="#000")
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        f_up = await _make_feature(db_session, epic, "Upstream", 1)
        f_down = await _make_feature(db_session, epic, "Downstream", 2)
        await _make_task(
            db_session,
            f_up,
            10,
            status="review",
            pr_url="https://github.com/x/y/pull/1",
        )
        downstream_task = await _make_task(db_session, f_down, 20)
        db_session.add(FeatureDependency(feature_id=f_down.id, depends_on_id=f_up.id))
        await db_session.commit()

        svc = BoardService(BoardRepository(db_session))
        # No artifact check required for task-level resolution rule
        assert await svc.get_unresolved_blockers(downstream_task.id) == []

    async def test_upstream_review_without_pr_url_stays_blocked(
        self, db_session: AsyncSession
    ) -> None:
        project = await _make_project(db_session)
        epic = Epic(project_id=project.id, title="E", position=0, color="#000")
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        f_up = await _make_feature(db_session, epic, "Upstream", 1)
        f_down = await _make_feature(db_session, epic, "Downstream", 2)
        await _make_task(db_session, f_up, 10, status="review", pr_url=None)
        downstream_task = await _make_task(db_session, f_down, 20)
        db_session.add(FeatureDependency(feature_id=f_down.id, depends_on_id=f_up.id))
        await db_session.commit()

        svc = BoardService(BoardRepository(db_session))
        blockers = await svc.get_unresolved_blockers(downstream_task.id)
        assert len(blockers) == 1
        assert blockers[0]["incomplete_task_numbers"] == [10]

    async def test_multiple_features_ordered_by_number(self, db_session: AsyncSession) -> None:
        """Stable order: by feature.number, not UUID."""
        project = await _make_project(db_session)
        epic = Epic(project_id=project.id, title="E", position=0, color="#000")
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        # Insert in reverse numeric order to prove we don't rely on insert order
        f3 = await _make_feature(db_session, epic, "F-3", 3)
        f2 = await _make_feature(db_session, epic, "F-2", 2)
        f1 = await _make_feature(db_session, epic, "F-1", 1)
        f_down = await _make_feature(db_session, epic, "Downstream", 99)

        await _make_task(db_session, f1, 11, status="backlog")
        await _make_task(db_session, f2, 21, status="backlog")
        await _make_task(db_session, f3, 31, status="backlog")
        downstream_task = await _make_task(db_session, f_down, 100)

        for up in (f1, f2, f3):
            db_session.add(FeatureDependency(feature_id=f_down.id, depends_on_id=up.id))
        await db_session.commit()

        svc = BoardService(BoardRepository(db_session))
        blockers = await svc.get_unresolved_blockers(downstream_task.id)
        numbers = [b["feature_number"] for b in blockers]
        assert numbers == [1, 2, 3]

    async def test_partial_feature_completion_lists_only_open_tasks(
        self, db_session: AsyncSession
    ) -> None:
        project = await _make_project(db_session)
        epic = Epic(project_id=project.id, title="E", position=0, color="#000")
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        f_up = await _make_feature(db_session, epic, "Upstream", 1)
        f_down = await _make_feature(db_session, epic, "Downstream", 2)
        await _make_task(db_session, f_up, 5, status="done")
        await _make_task(db_session, f_up, 7, status="backlog")
        await _make_task(db_session, f_up, 3, status="backlog")
        downstream_task = await _make_task(db_session, f_down, 100)
        db_session.add(FeatureDependency(feature_id=f_down.id, depends_on_id=f_up.id))
        await db_session.commit()

        svc = BoardService(BoardRepository(db_session))
        blockers = await svc.get_unresolved_blockers(downstream_task.id)
        assert len(blockers) == 1
        assert blockers[0]["incomplete_task_numbers"] == [3, 7]
