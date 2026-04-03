"""Database queries for the Board bounded context."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.board.models import Epic, Feature, Project, Task


class BoardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Project ---

    async def create_project(self, name: str, description: str, repo_url: str) -> Project:
        project = Project(name=name, description=description, repo_url=repo_url)
        self._session.add(project)
        await self._session.commit()
        await self._session.refresh(project)
        return project

    async def get_project(self, project_id: UUID) -> Project | None:
        return await self._session.get(Project, project_id)

    async def list_projects(self) -> list[Project]:
        result = await self._session.execute(select(Project).order_by(Project.created_at))
        return list(result.scalars().all())

    async def set_project_api_key_hash(self, project_id: UUID, api_key_hash: str) -> None:
        project = await self._session.get(Project, project_id)
        if project:
            project.api_key_hash = api_key_hash
            await self._session.commit()

    async def get_project_by_api_key_hash(self, api_key_hash: str) -> Project | None:
        result = await self._session.execute(
            select(Project).where(Project.api_key_hash == api_key_hash)
        )
        return result.scalar_one_or_none()

    # --- Epic ---

    async def create_epic(
        self,
        project_id: UUID,
        title: str,
        description: str,
        bounded_context: str,
        context_description: str,
        position: int,
    ) -> Epic:
        epic = Epic(
            project_id=project_id,
            title=title,
            description=description,
            bounded_context=bounded_context,
            context_description=context_description,
            position=position,
        )
        self._session.add(epic)
        await self._session.commit()
        await self._session.refresh(epic)
        return epic

    async def list_epics(self, project_id: UUID) -> list[Epic]:
        result = await self._session.execute(
            select(Epic).where(Epic.project_id == project_id).order_by(Epic.position)
        )
        return list(result.scalars().all())

    async def get_epic(self, epic_id: UUID) -> Epic | None:
        return await self._session.get(Epic, epic_id)

    # --- Feature ---

    async def create_feature(
        self, epic_id: UUID, title: str, description: str, position: int
    ) -> Feature:
        feature = Feature(epic_id=epic_id, title=title, description=description, position=position)
        self._session.add(feature)
        await self._session.commit()
        await self._session.refresh(feature)
        return feature

    async def list_features(self, epic_id: UUID) -> list[Feature]:
        result = await self._session.execute(
            select(Feature).where(Feature.epic_id == epic_id).order_by(Feature.position)
        )
        return list(result.scalars().all())

    async def get_feature(self, feature_id: UUID) -> Feature | None:
        return await self._session.get(Feature, feature_id)

    # --- Task ---

    async def create_task(
        self,
        feature_id: UUID,
        title: str,
        description: str,
        priority: str,
        position: int,
    ) -> Task:
        task = Task(
            feature_id=feature_id,
            title=title,
            description=description,
            priority=priority,
            position=position,
        )
        self._session.add(task)
        await self._session.commit()
        await self._session.refresh(task)
        return task

    async def get_task(self, task_id: UUID) -> Task | None:
        return await self._session.get(Task, task_id)

    async def update_task(self, task_id: UUID, **fields: object) -> Task | None:
        task = await self._session.get(Task, task_id)
        if task is None:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(task, key, value)
        await self._session.commit()
        await self._session.refresh(task)
        return task

    async def delete_task(self, task_id: UUID) -> bool:
        task = await self._session.get(Task, task_id)
        if task is None:
            return False
        await self._session.delete(task)
        await self._session.commit()
        return True

    async def get_board_tasks(self, project_id: UUID) -> list[Task]:
        """Get all tasks for a project with their feature/epic info loaded."""
        result = await self._session.execute(
            select(Task)
            .join(Feature, Task.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Epic.project_id == project_id)
            .options(joinedload(Task.feature).joinedload(Feature.epic))
            .order_by(Task.position)
        )
        return list(result.unique().scalars().all())

    async def get_tasks_for_feature(self, feature_id: UUID) -> list[Task]:
        result = await self._session.execute(
            select(Task).where(Task.feature_id == feature_id).order_by(Task.position)
        )
        return list(result.scalars().all())

    async def get_tasks_for_worktree(self, worktree_id: UUID) -> list[Task]:
        result = await self._session.execute(
            select(Task).where(Task.worktree_id == worktree_id).order_by(Task.position)
        )
        return list(result.scalars().all())
