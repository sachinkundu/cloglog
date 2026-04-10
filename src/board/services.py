"""Business logic for the Board bounded context."""

from __future__ import annotations

import hashlib
import secrets
from uuid import UUID

from src.board.models import Project, Task
from src.board.repository import BoardRepository
from src.board.schemas import ImportPlan, SearchResponse, SearchResult
from src.document.models import Document

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

    # --- Auto-Attach Document ---

    async def auto_attach_document_on_review(self, task: Task, pr_url: str) -> Document | None:
        """Auto-create a document linking pr_url to the parent feature.

        Called when a spec/plan task moves to review.
        Returns the created Document, or None if conditions aren't met.
        """
        if task.task_type not in ("spec", "plan"):
            return None

        feature = await self._repo.get_feature(task.feature_id)
        if feature is None:
            return None

        # Avoid duplicates: check if this pr_url is already attached
        session = self._repo._session
        from sqlalchemy import select

        existing = await session.execute(
            select(Document).where(
                Document.attached_to_type == "feature",
                Document.attached_to_id == task.feature_id,
                Document.source_path == pr_url,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return None

        doc_type = "design_spec" if task.task_type == "spec" else "implementation_plan"
        title = f"{task.task_type.capitalize()} — {task.title}"

        doc = Document(
            title=title,
            content="",
            doc_type=doc_type,
            source_path=pr_url,
            attached_to_type="feature",
            attached_to_id=task.feature_id,
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)
        return doc

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

    # --- Dependencies ---

    async def has_cycle(self, feature_id: UUID, depends_on_id: UUID) -> bool:
        """DFS from depends_on_id's own dependencies. If we reach feature_id, there's a cycle."""
        visited: set[UUID] = set()
        stack = [depends_on_id]
        while stack:
            current = stack.pop()
            if current == feature_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            deps = await self._repo.get_feature_dependencies(current)
            stack.extend(deps)
        return False

    async def add_dependency(self, feature_id: UUID, depends_on_id: UUID) -> None:
        if feature_id == depends_on_id:
            raise ValueError("A feature cannot depend on itself")
        feature = await self._repo.get_feature(feature_id)
        depends_on = await self._repo.get_feature(depends_on_id)
        if feature is None or depends_on is None:
            raise ValueError("Feature not found")
        epic_a = await self._repo.get_epic(feature.epic_id)
        epic_b = await self._repo.get_epic(depends_on.epic_id)
        assert epic_a is not None and epic_b is not None
        if epic_a.project_id != epic_b.project_id:
            raise ValueError("Features must be in the same project")
        if await self._repo.get_dependency_exists(feature_id, depends_on_id):
            raise ValueError("DUPLICATE")
        if await self.has_cycle(feature_id, depends_on_id):
            raise ValueError("Adding this dependency would create a cycle")
        await self._repo.add_dependency(feature_id, depends_on_id)

    async def remove_dependency(self, feature_id: UUID, depends_on_id: UUID) -> bool:
        return await self._repo.remove_dependency(feature_id, depends_on_id)

    async def get_dependency_graph(self, project_id: UUID) -> dict[str, object]:
        epics = await self._repo.get_backlog_tree(project_id)
        edges = await self._repo.get_all_dependencies(project_id)
        nodes = []
        for epic in epics:
            for feature in epic.features:
                nodes.append(
                    {
                        "id": str(feature.id),
                        "number": feature.number,
                        "title": feature.title,
                        "status": feature.status,
                        "epic_title": epic.title,
                        "epic_color": epic.color,
                    }
                )
        edge_list = []
        number_map = {n["id"]: n["number"] for n in nodes}
        for feat_id, dep_id in edges:
            edge_list.append(
                {
                    "from_id": str(dep_id),
                    "to_id": str(feat_id),
                    "from_number": number_map.get(str(dep_id), 0),
                    "to_number": number_map.get(str(feat_id), 0),
                }
            )
        return {"nodes": nodes, "edges": edge_list}

    # --- Search ---

    async def search(
        self,
        project_id: UUID,
        query: str,
        limit: int = 20,
        *,
        status_filter: list[str] | None = None,
    ) -> SearchResponse:
        project = await self._repo.get_project(project_id)
        if not project:
            raise ValueError("Project not found")
        results, total = await self._repo.search(
            project_id, query, limit, status_filter=status_filter
        )
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
