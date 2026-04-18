"""Database queries for the Board bounded context."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
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

    async def delete_project(self, project_id: UUID) -> bool:
        """Delete a project. Caller must remove agent worktrees first."""
        project = await self._session.get(Project, project_id)
        if project is None:
            return False
        await self._session.delete(project)
        await self._session.commit()
        return True

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

    async def update_epic(self, epic_id: UUID, **fields: object) -> Epic | None:
        epic = await self._session.get(Epic, epic_id)
        if epic is None:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(epic, key, value)
        await self._session.commit()
        await self._session.refresh(epic)
        return epic

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

    async def update_feature(self, feature_id: UUID, **fields: object) -> Feature | None:
        feature = await self._session.get(Feature, feature_id)
        if feature is None:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(feature, key, value)
        await self._session.commit()
        await self._session.refresh(feature)
        return feature

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
        task_type: str = "task",
    ) -> Task:
        task = Task(
            feature_id=feature_id,
            title=title,
            description=description,
            priority=priority,
            position=position,
            number=number,
            task_type=task_type,
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

    async def get_board_tasks(
        self,
        project_id: UUID,
        *,
        statuses: list[str] | None = None,
        epic_id: UUID | None = None,
        exclude_done: bool = False,
    ) -> list[Task]:
        """Get tasks for a project with their feature/epic info loaded.

        Args:
            statuses: If provided, only return tasks with these statuses.
            epic_id: If provided, only return tasks under this epic.
            exclude_done: If True, exclude tasks with status 'done'.
        """
        query = (
            select(Task)
            .join(Feature, Task.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Epic.project_id == project_id, Task.retired == False)  # noqa: E712
            .options(joinedload(Task.feature).joinedload(Feature.epic))
        )
        if statuses:
            query = query.where(Task.status.in_(statuses))
        if epic_id is not None:
            query = query.where(Epic.id == epic_id)
        if exclude_done:
            query = query.where(Task.status != "done")
        query = query.order_by(Feature.position, Task.position)
        result = await self._session.execute(query)
        return list(result.unique().scalars().all())

    async def get_active_tasks(self, project_id: UUID) -> list[Task]:
        """Get non-done, non-archived tasks with feature/epic info loaded."""
        query = (
            select(Task)
            .join(Feature, Task.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(
                Epic.project_id == project_id,
                Task.status != "done",
                Task.archived == False,  # noqa: E712
                Task.retired == False,  # noqa: E712
            )
            .options(joinedload(Task.feature).joinedload(Feature.epic))
            .order_by(Task.position)
        )
        result = await self._session.execute(query)
        return list(result.unique().scalars().all())

    async def get_backlog_tree(self, project_id: UUID) -> list[Epic]:
        """Get all epics with features and non-retired tasks eager-loaded."""
        result = await self._session.execute(
            select(Epic)
            .where(Epic.project_id == project_id)
            .options(joinedload(Epic.features).joinedload(Feature.tasks))
            .order_by(Epic.position)
        )
        epics = list(result.unique().scalars().all())
        for epic in epics:
            for feature in epic.features:
                feature.tasks = [t for t in feature.tasks if not t.retired]
        return epics

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

    async def retire_done_tasks(self, project_id: UUID) -> int:
        """Retire all archived done tasks for a project. Returns count retired."""
        from sqlalchemy import CursorResult, update

        result = await self._session.execute(
            update(Task)
            .where(
                Task.feature_id.in_(
                    select(Feature.id)
                    .join(Epic, Feature.epic_id == Epic.id)
                    .where(Epic.project_id == project_id)
                ),
                Task.status == "done",
                Task.archived == True,  # noqa: E712
                Task.retired == False,  # noqa: E712
            )
            .values(retired=True)
        )
        await self._session.commit()
        assert isinstance(result, CursorResult)
        return int(result.rowcount)

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

    # --- PR Lookup ---

    async def find_task_by_pr_url(self, pr_url: str) -> Task | None:
        """Find a task by its PR URL. Returns the most recently updated match."""
        stmt = (
            select(Task)
            .where(Task.pr_url == pr_url)
            .where(Task.status.in_(["in_progress", "review"]))
            .order_by(Task.updated_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_task_by_pr_url_for_project(self, pr_url: str, project_id: UUID) -> Task | None:
        """Find a task by PR URL scoped to a specific project.

        Prevents cross-project pr_merged manipulation: an agent in project A
        cannot affect tasks in project B.
        """
        stmt = (
            select(Task)
            .join(Feature, Task.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Task.pr_url == pr_url)
            .where(Task.status.in_(["in_progress", "review"]))
            .where(Epic.project_id == project_id)
            .order_by(Task.updated_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_project_by_repo(self, repo_full_name: str) -> Project | None:
        """Find a project by GitHub repo full name.

        Project.repo_url stores the full URL (e.g. 'https://github.com/sachinkundu/cloglog').
        This method matches against the trailing repo_full_name (e.g. 'sachinkundu/cloglog').
        """
        stmt = select(Project).where(Project.repo_url.endswith(repo_full_name)).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # --- Search ---

    # Status groups for GitHub-style is: qualifiers
    STATUS_OPEN = ("backlog", "in_progress", "review")
    STATUS_CLOSED = ("done",)

    async def search(
        self,
        project_id: UUID,
        query: str,
        limit: int = 20,
        *,
        status_filter: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Search epics, features, and tasks by title or entity number.

        Supports patterns like "E-1", "F-21", "T-3", "1", or free text.
        Optional status_filter restricts task results by status.
        Returns (results, total_count).
        """
        # Parse query for entity number pattern (e.g. E-1, F-21, T-3, or bare 1)
        number_match = re.match(r"^([EFT])?-?(\d+)$", query.strip(), re.IGNORECASE)
        type_prefix: str | None = None
        exact_number: str = ""

        if number_match:
            type_prefix = (number_match.group(1) or "").upper() or None
            exact_number = number_match.group(2)

        pattern = f"%{query}%"

        # Build status filter SQL clause for tasks
        task_status_clause = ""
        params: dict[str, Any] = {
            "project_id": project_id,
            "pattern": pattern,
            "exact_number": exact_number,
        }
        if status_filter:
            placeholders = ", ".join(f":sf_{i}" for i in range(len(status_filter)))
            task_status_clause = f" AND t.status IN ({placeholders})"
            for i, s in enumerate(status_filter):
                params[f"sf_{i}"] = s

        # Build individual SELECT statements
        epic_select = """
            SELECT e.id, 'epic' AS type, e.title, e.number, e.status,
                   NULL AS epic_title, NULL AS epic_color, NULL AS feature_title,
                   1 AS type_priority
            FROM epics e
            WHERE e.project_id = :project_id
              AND (e.title ILIKE :pattern OR e.number::text = :exact_number)
        """

        feature_select = """
            SELECT f.id, 'feature' AS type, f.title, f.number, f.status,
                   e.title AS epic_title, e.color AS epic_color, NULL AS feature_title,
                   2 AS type_priority
            FROM features f
            JOIN epics e ON f.epic_id = e.id
            WHERE e.project_id = :project_id
              AND (f.title ILIKE :pattern OR f.number::text = :exact_number)
        """

        task_select = f"""
            SELECT t.id, 'task' AS type, t.title, t.number, t.status,
                   e.title AS epic_title, e.color AS epic_color, f.title AS feature_title,
                   3 AS type_priority
            FROM tasks t
            JOIN features f ON t.feature_id = f.id
            JOIN epics e ON f.epic_id = e.id
            WHERE e.project_id = :project_id
              AND (t.title ILIKE :pattern OR t.number::text = :exact_number)
              {task_status_clause}
        """

        # When status_filter is set, only search tasks (epics/features don't have
        # the same status semantics).
        if status_filter:
            union_sql = task_select
        elif type_prefix == "E":
            union_sql = epic_select
        elif type_prefix == "F":
            union_sql = feature_select
        elif type_prefix == "T":
            union_sql = task_select
        else:
            union_sql = f"{epic_select} UNION ALL {feature_select} UNION ALL {task_select}"

        # Count query
        count_sql = f"SELECT COUNT(*) FROM ({union_sql}) AS search_results"
        count_result = await self._session.execute(text(count_sql), params)
        total = count_result.scalar_one()

        # Results query with ordering and limit
        results_sql = f"""
            SELECT id, type, title, number, status, epic_title, epic_color, feature_title
            FROM ({union_sql}) AS search_results
            ORDER BY type_priority, title
            LIMIT :limit
        """
        results_result = await self._session.execute(
            text(results_sql),
            {**params, "limit": limit},
        )

        rows = results_result.fetchall()
        results = [
            {
                "id": row[0],
                "type": row[1],
                "title": row[2],
                "number": row[3],
                "status": row[4],
                "epic_title": row[5],
                "epic_color": row[6],
                "feature_title": row[7],
            }
            for row in rows
        ]

        return results, total

    # --- Reorder ---

    async def reorder_epics(self, project_id: UUID, positions: list[tuple[UUID, int]]) -> None:
        """Reorder epics within a project by updating their positions."""
        ids = [pid for pid, _ in positions]
        result = await self._session.execute(
            select(Epic).where(Epic.project_id == project_id, Epic.id.in_(ids))
        )
        epics = {e.id: e for e in result.scalars().all()}
        if len(epics) != len(ids):
            missing = set(ids) - set(epics.keys())
            raise ValueError(f"Epic IDs not found in project: {missing}")
        for epic_id, pos in positions:
            epics[epic_id].position = pos
        await self._session.commit()

    async def reorder_features(self, epic_id: UUID, positions: list[tuple[UUID, int]]) -> None:
        """Reorder features within an epic by updating their positions."""
        ids = [pid for pid, _ in positions]
        result = await self._session.execute(
            select(Feature).where(Feature.epic_id == epic_id, Feature.id.in_(ids))
        )
        features = {f.id: f for f in result.scalars().all()}
        if len(features) != len(ids):
            missing = set(ids) - set(features.keys())
            raise ValueError(f"Feature IDs not found in epic: {missing}")
        for feature_id, pos in positions:
            features[feature_id].position = pos
        await self._session.commit()

    async def get_max_task_position(self, feature_id: UUID, status: str) -> int:
        """Get the maximum position among tasks with a given status in a feature."""
        result = await self._session.execute(
            select(func.max(Task.position)).where(
                Task.feature_id == feature_id, Task.status == status
            )
        )
        return result.scalar_one() or 0

    async def reorder_tasks(self, feature_id: UUID, positions: list[tuple[UUID, int]]) -> None:
        """Reorder tasks within a feature by updating their positions."""
        ids = [pid for pid, _ in positions]
        result = await self._session.execute(
            select(Task).where(Task.feature_id == feature_id, Task.id.in_(ids))
        )
        tasks = {t.id: t for t in result.scalars().all()}
        if len(tasks) != len(ids):
            missing = set(ids) - set(tasks.keys())
            raise ValueError(f"Task IDs not found in feature: {missing}")
        for task_id, pos in positions:
            tasks[task_id].position = pos
        await self._session.commit()
