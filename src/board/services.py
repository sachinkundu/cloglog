"""Business logic for the Board bounded context."""

from __future__ import annotations

import hashlib
import secrets
from uuid import UUID

from src.board.models import Project
from src.board.repository import BoardRepository
from src.board.schemas import ImportPlan, SearchResponse, SearchResult

EPIC_COLOR_PALETTE = [
    "#7c3aed",  # purple
    "#0ea5e9",  # cyan
    "#f59e0b",  # amber
    "#10b981",  # emerald
    "#ef4444",  # red
    "#ec4899",  # pink
    "#6366f1",  # indigo
    "#14b8a6",  # teal
    "#f97316",  # orange
    "#8b5cf6",  # violet
]


class BoardService:
    def __init__(self, repo: BoardRepository) -> None:
        self._repo = repo

    # --- API Key ---

    async def create_project(
        self, name: str, description: str, repo_url: str
    ) -> tuple[Project, str]:
        """Create a project and return (project, plaintext_api_key)."""
        project = await self._repo.create_project(name, description, repo_url)
        api_key = secrets.token_hex(32)
        api_key_hash = self._hash_key(api_key)
        await self._repo.set_project_api_key_hash(project.id, api_key_hash)
        # Refresh to get the updated hash
        refreshed = await self._repo.get_project(project.id)
        assert refreshed is not None
        return refreshed, api_key

    async def verify_api_key(self, api_key: str) -> Project | None:
        """Verify an API key and return the associated project."""
        api_key_hash = self._hash_key(api_key)
        return await self._repo.get_project_by_api_key_hash(api_key_hash)

    @staticmethod
    def _hash_key(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    # --- Status Roll-Up ---

    async def recompute_rollup(self, feature_id: UUID) -> None:
        """Recompute feature status from tasks, then epic status from features."""
        tasks = await self._repo.get_tasks_for_feature(feature_id)
        feature = await self._repo.get_feature(feature_id)
        if feature is None:
            return

        # Feature status roll-up from tasks
        statuses = [t.status for t in tasks]
        if all(s == "done" for s in statuses):
            feature.status = "done"
        elif any(s == "review" for s in statuses):
            feature.status = "review"
        elif any(s == "in_progress" for s in statuses):
            feature.status = "in_progress"
        else:
            feature.status = "planned"

        session = self._repo._session
        await session.commit()

        # Epic status roll-up from features
        epic = await self._repo.get_epic(feature.epic_id)
        if epic is None:
            return

        features = await self._repo.list_features(epic.id)
        feature_statuses = [f.status for f in features]
        if all(s == "done" for s in feature_statuses):
            epic.status = "done"
        elif any(s in ("in_progress", "review") for s in feature_statuses):
            epic.status = "in_progress"
        else:
            epic.status = "planned"

        await session.commit()

    # --- Search ---

    async def search(
        self, project_id: UUID, query: str, limit: int = 20
    ) -> SearchResponse:
        project = await self._repo.get_project(project_id)
        if not project:
            raise ValueError("Project not found")
        results, total = await self._repo.search(project_id, query, limit)
        return SearchResponse(
            query=query,
            results=[SearchResult(**r) for r in results],
            total=total,
        )

    # --- Import ---

    async def import_plan(self, project_id: UUID, plan: ImportPlan) -> dict[str, int]:
        """Bulk import epics/features/tasks from a structured plan."""
        epics_created = 0
        features_created = 0
        tasks_created = 0

        existing_count = await self._repo.count_epics(project_id)
        next_epic_num = await self._repo.next_epic_number(project_id)
        next_feat_num = await self._repo.next_feature_number(project_id)
        next_task_num = await self._repo.next_task_number(project_id)

        for epic_pos, epic_data in enumerate(plan.epics):
            color = EPIC_COLOR_PALETTE[(existing_count + epic_pos) % len(EPIC_COLOR_PALETTE)]
            epic = await self._repo.create_epic(
                project_id=project_id,
                title=epic_data.title,
                description=epic_data.description,
                bounded_context=epic_data.bounded_context,
                context_description="",
                position=epic_pos,
                color=color,
                number=next_epic_num,
            )
            next_epic_num += 1
            epics_created += 1

            for feat_pos, feat_data in enumerate(epic_data.features):
                feature = await self._repo.create_feature(
                    epic_id=epic.id,
                    title=feat_data.title,
                    description=feat_data.description,
                    position=feat_pos,
                    number=next_feat_num,
                )
                next_feat_num += 1
                features_created += 1

                for task_pos, task_data in enumerate(feat_data.tasks):
                    await self._repo.create_task(
                        feature_id=feature.id,
                        title=task_data.title,
                        description=task_data.description,
                        priority=task_data.priority,
                        position=task_pos,
                        number=next_task_num,
                    )
                    next_task_num += 1
                    tasks_created += 1

        return {
            "epics_created": epics_created,
            "features_created": features_created,
            "tasks_created": tasks_created,
        }
