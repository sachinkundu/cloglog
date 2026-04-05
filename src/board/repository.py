"""Database queries for the Board bounded context."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.board.models import Epic, Feature, FeatureDependency, Notification, Project, Task, TaskNote


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

    async def count_epics(self, project_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Epic).where(Epic.project_id == project_id)
        )
        return result.scalar_one()

    async def next_epic_number(self, project_id: UUID) -> int:
        """Get and increment the monotonic epic counter on the project."""
        project = await self._session.get(Project, project_id)
        assert project is not None
        num = project.next_epic_num
        project.next_epic_num = num + 1
        await self._session.flush()
        return num

    async def next_feature_number(self, project_id: UUID) -> int:
        """Get and increment the monotonic feature counter on the project."""
        project = await self._session.get(Project, project_id)
        assert project is not None
        num = project.next_feature_num
        project.next_feature_num = num + 1
        await self._session.flush()
        return num

    async def next_task_number(self, project_id: UUID) -> int:
        """Get and increment the monotonic task counter on the project."""
        project = await self._session.get(Project, project_id)
        assert project is not None
        num = project.next_task_num
        project.next_task_num = num + 1
        await self._session.flush()
        return num

    async def create_epic(
        self,
        project_id: UUID,
        title: str,
        description: str,
        bounded_context: str,
        context_description: str,
        position: int,
        color: str = "",
        number: int = 0,
    ) -> Epic:
        epic = Epic(
            project_id=project_id,
            title=title,
            description=description,
            bounded_context=bounded_context,
            context_description=context_description,
            position=position,
            color=color,
            number=number,
        )
        self._session.add(epic)
        await self._session.commit()
        await self._session.refresh(epic)
        return epic

    async def backfill_epic_colors(self, project_id: UUID, palette: list[str]) -> int:
        """Assign colors to epics that have an empty color field. Returns count updated."""
        result = await self._session.execute(
            select(Epic)
            .where(Epic.project_id == project_id, Epic.color == "")
            .order_by(Epic.position)
        )
        epics = list(result.scalars().all())
        if not epics:
            return 0
        # Count existing colored epics to continue the palette rotation
        count_result = await self._session.execute(
            select(func.count())
            .select_from(Epic)
            .where(Epic.project_id == project_id, Epic.color != "")
        )
        offset = count_result.scalar_one()
        for i, epic in enumerate(epics):
            epic.color = palette[(offset + i) % len(palette)]
        await self._session.commit()
        return len(epics)

    async def list_epics(self, project_id: UUID) -> list[Epic]:
        result = await self._session.execute(
            select(Epic).where(Epic.project_id == project_id).order_by(Epic.position)
        )
        return list(result.scalars().all())

    async def get_epic(self, epic_id: UUID) -> Epic | None:
        return await self._session.get(Epic, epic_id)

    async def delete_epic(self, epic_id: UUID) -> bool:
        epic = await self._session.get(Epic, epic_id)
        if epic is None:
            return False
        await self._session.delete(epic)
        await self._session.commit()
        return True

    # --- Feature ---

    async def create_feature(
        self, epic_id: UUID, title: str, description: str, position: int, number: int = 0
    ) -> Feature:
        feature = Feature(
            epic_id=epic_id,
            title=title,
            description=description,
            position=position,
            number=number,
        )
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

    async def delete_feature(self, feature_id: UUID) -> bool:
        feature = await self._session.get(Feature, feature_id)
        if feature is None:
            return False
        await self._session.delete(feature)
        await self._session.commit()
        return True

    # --- Task ---

    async def create_task(
        self,
        feature_id: UUID,
        title: str,
        description: str,
        priority: str,
        position: int,
        number: int = 0,
    ) -> Task:
        task = Task(
            feature_id=feature_id,
            title=title,
            description=description,
            priority=priority,
            position=position,
            number=number,
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

    async def get_backlog_tree(self, project_id: UUID) -> list[Epic]:
        """Get all epics with features and tasks eager-loaded for the backlog tree."""
        result = await self._session.execute(
            select(Epic)
            .where(Epic.project_id == project_id)
            .options(joinedload(Epic.features).joinedload(Feature.tasks))
            .order_by(Epic.position)
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

    # --- Dependencies ---

    async def add_dependency(self, feature_id: UUID, depends_on_id: UUID) -> None:
        dep = FeatureDependency(feature_id=feature_id, depends_on_id=depends_on_id)
        self._session.add(dep)
        await self._session.commit()

    async def remove_dependency(self, feature_id: UUID, depends_on_id: UUID) -> bool:
        dep = await self._session.get(FeatureDependency, (feature_id, depends_on_id))
        if dep is None:
            return False
        await self._session.delete(dep)
        await self._session.commit()
        return True

    async def get_dependency_exists(self, feature_id: UUID, depends_on_id: UUID) -> bool:
        dep = await self._session.get(FeatureDependency, (feature_id, depends_on_id))
        return dep is not None

    async def get_all_dependencies(self, project_id: UUID) -> list[tuple[UUID, UUID]]:
        result = await self._session.execute(
            select(FeatureDependency.feature_id, FeatureDependency.depends_on_id)
            .join(Feature, FeatureDependency.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Epic.project_id == project_id)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def get_feature_dependencies(self, feature_id: UUID) -> list[UUID]:
        result = await self._session.execute(
            select(FeatureDependency.depends_on_id).where(
                FeatureDependency.feature_id == feature_id
            )
        )
        return [row[0] for row in result.all()]

    # --- Task Notes ---

    async def add_task_note(self, task_id: UUID, note: str) -> TaskNote:
        task_note = TaskNote(task_id=task_id, note=note)
        self._session.add(task_note)
        await self._session.commit()
        await self._session.refresh(task_note)
        return task_note

    async def get_task_notes(self, task_id: UUID) -> list[TaskNote]:
        result = await self._session.execute(
            select(TaskNote).where(TaskNote.task_id == task_id).order_by(TaskNote.created_at)
        )
        return list(result.scalars().all())

    # --- Notifications ---

    async def create_notification(
        self, project_id: UUID, task_id: UUID, task_title: str, task_number: int
    ) -> Notification:
        notif = Notification(
            project_id=project_id,
            task_id=task_id,
            task_title=task_title,
            task_number=task_number,
        )
        self._session.add(notif)
        await self._session.commit()
        await self._session.refresh(notif)
        return notif

    async def get_unread_notifications(self, project_id: UUID) -> list[Notification]:
        result = await self._session.execute(
            select(Notification)
            .where(Notification.project_id == project_id, Notification.read == False)  # noqa: E712
            .order_by(Notification.created_at.desc())
        )
        return list(result.scalars().all())

    async def mark_notification_read(self, notification_id: UUID) -> Notification | None:
        notif = await self._session.get(Notification, notification_id)
        if notif is None:
            return None
        notif.read = True
        await self._session.commit()
        await self._session.refresh(notif)
        return notif

    async def mark_all_notifications_read(self, project_id: UUID) -> int:
        from sqlalchemy import CursorResult, update

        result = await self._session.execute(
            update(Notification)
            .where(
                Notification.project_id == project_id,
                Notification.read == False,  # noqa: E712
            )
            .values(read=True)
        )
        await self._session.commit()
        assert isinstance(result, CursorResult)
        return int(result.rowcount)

    async def get_unread_notification_for_task(
        self, project_id: UUID, task_id: UUID
    ) -> Notification | None:
        result = await self._session.execute(
            select(Notification).where(
                Notification.project_id == project_id,
                Notification.task_id == task_id,
                Notification.read == False,  # noqa: E712
            )
        )
        return result.scalars().first()
