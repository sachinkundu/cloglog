"""Business logic for the Board bounded context."""

from __future__ import annotations

import hashlib
import secrets
from uuid import UUID

from src.board.interfaces import BoardBlockerDTO, FeatureBlocker, TaskBlocker
from src.board.models import Feature, Project, Task
from src.board.repo_url import normalize_repo_url
from src.board.repository import BoardRepository
from src.board.schemas import ImportPlan, SearchResponse, SearchResult
from src.board.templates import (
    CLOSE_OFF_EPIC_TITLE,
    CLOSE_OFF_FEATURE_TITLE,
    close_worktree_template,
)
from src.document.models import Document


def _task_resolved(task: Task) -> bool:
    """A task counts as resolved (for dependency purposes) when it is done,
    or in review with a PR URL.

    Note: artifact-attachment is *not* checked here — that check belongs to
    the pipeline-predecessor rule (spec→plan→impl) which Agent owns, not to
    arbitrary ``blocked_by`` edges. See F-11 spec §"Ubiquitous Language".
    """
    if task.status == "done":
        return True
    return task.status == "review" and bool(task.pr_url)


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
        project = await self._repo.create_project(name, description, normalize_repo_url(repo_url))
        api_key = secrets.token_hex(32)
        api_key_hash = self._hash_key(api_key)
        await self._repo.set_project_api_key_hash(project.id, api_key_hash)
        # Refresh to get the updated hash
        refreshed = await self._repo.get_project(project.id)
        assert refreshed is not None
        return refreshed, api_key

    async def update_project(self, project_id: UUID, fields: dict[str, object]) -> Project | None:
        """Patch project fields. ``repo_url``, when present, is canonicalized.

        ``fields`` is the route's ``model_dump(exclude_unset=True)`` — only
        keys the caller explicitly sent. The ``Project.repo_url`` column is
        NOT NULL with a default of ``""`` (see ``src/board/models.py``); an
        explicit JSON ``null`` is coerced to the empty string here so callers
        get a deterministic "clear" semantics instead of a 500 from
        Postgres' ``NotNullViolationError``.
        """
        if "repo_url" in fields:
            value = fields["repo_url"]
            fields = {**fields, "repo_url": normalize_repo_url(str(value)) if value else ""}
        return await self._repo.update_project(project_id, **fields)

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
        elif any(s in ("in_progress", "prioritized") for s in statuses):
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

    # --- Retire ---

    async def retire_all_done(self, project_id: UUID) -> int:
        """Retire all archived done tasks for a project. Returns count retired."""
        return await self._repo.retire_done_tasks(project_id)

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

    # --- Task Dependencies ---

    async def has_task_cycle(self, task_id: UUID, depends_on_task_id: UUID) -> bool:
        """DFS from the candidate upstream's own deps — if we reach
        ``task_id`` the new edge would close a cycle."""
        visited: set[UUID] = set()
        stack = [depends_on_task_id]
        while stack:
            current = stack.pop()
            if current == task_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            stack.extend(await self._repo.get_task_dependencies(current))
        return False

    async def _task_project_id(self, task_id: UUID) -> UUID | None:
        task = await self._repo.get_task(task_id)
        if task is None:
            return None
        feature = await self._repo.get_feature(task.feature_id)
        if feature is None:
            return None
        epic = await self._repo.get_epic(feature.epic_id)
        return None if epic is None else epic.project_id

    async def add_task_dependency(self, task_id: UUID, depends_on_task_id: UUID) -> None:
        if task_id == depends_on_task_id:
            raise ValueError("A task cannot depend on itself")
        pid_a = await self._task_project_id(task_id)
        pid_b = await self._task_project_id(depends_on_task_id)
        if pid_a is None or pid_b is None:
            raise ValueError("Task not found")
        if pid_a != pid_b:
            raise ValueError("Tasks must be in the same project")
        if await self._repo.get_task_dependency_exists(task_id, depends_on_task_id):
            raise ValueError("DUPLICATE")
        if await self.has_task_cycle(task_id, depends_on_task_id):
            raise ValueError("Adding this dependency would create a cycle")
        await self._repo.add_task_dependency(task_id, depends_on_task_id)

    async def remove_task_dependency(self, task_id: UUID, depends_on_task_id: UUID) -> bool:
        return await self._repo.remove_task_dependency(task_id, depends_on_task_id)

    async def get_unresolved_blockers(self, task_id: UUID) -> list[BoardBlockerDTO]:
        """Return feature and task blockers for ``task_id`` in stable order.

        Emits one ``FeatureBlocker`` per upstream feature that still has
        incomplete tasks (sorted by ``feature.number``), then one
        ``TaskBlocker`` per unresolved direct ``blocked_by`` edge (sorted
        by ``task.number``). Only direct edges — the transitive closure
        is implied by the direct edges still being unresolved, so
        including transitive would produce noisy duplicates.
        """
        task = await self._repo.get_task(task_id)
        if task is None:
            return []
        feature = await self._repo.get_feature(task.feature_id)
        if feature is None:
            return []

        blockers: list[BoardBlockerDTO] = []

        # Feature-level (T-36 scope)
        dep_feature_ids = await self._repo.get_feature_dependencies(feature.id)
        dep_features: list[Feature] = []
        for fid in dep_feature_ids:
            f = await self._repo.get_feature(fid)
            if f is not None:
                dep_features.append(f)
        for dep_feature in sorted(dep_features, key=lambda f: f.number):
            dep_tasks = await self._repo.get_tasks_for_feature(dep_feature.id)
            incomplete = [t for t in dep_tasks if not _task_resolved(t)]
            if incomplete:
                blockers.append(
                    FeatureBlocker(
                        kind="feature",
                        feature_id=str(dep_feature.id),
                        feature_number=dep_feature.number,
                        feature_title=dep_feature.title,
                        incomplete_task_numbers=sorted(t.number for t in incomplete),
                    )
                )

        # Task-level (T-224 scope)
        dep_task_ids = await self._repo.get_task_dependencies(task_id)
        dep_task_rows: list[Task] = []
        for tid in dep_task_ids:
            t = await self._repo.get_task(tid)
            if t is not None:
                dep_task_rows.append(t)
        for dep_task in sorted(dep_task_rows, key=lambda t: t.number):
            if _task_resolved(dep_task):
                continue
            blockers.append(
                TaskBlocker(
                    kind="task",
                    task_id=str(dep_task.id),
                    task_number=dep_task.number,
                    task_title=dep_task.title,
                    status=dep_task.status,
                )
            )

        return blockers

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

    # --- Close-off tasks ---

    async def create_close_off_task(
        self,
        project_id: UUID,
        close_off_worktree_id: UUID,
        worktree_name: str,
        *,
        main_agent_worktree_id: UUID | None = None,
    ) -> tuple[Task, bool]:
        """Find-or-create the close-off task for a worktree.

        Idempotent on ``close_off_worktree_id``. Returns ``(task, created)``
        where ``created`` is False for idempotent hits. Auto-provisions an
        "Operations" epic and "Worktree Close-off" feature on first use so
        the caller (``on-worktree-create.sh``) does not need to know about
        the board hierarchy.
        """
        existing = await self._repo.find_close_off_task(close_off_worktree_id)
        if existing is not None:
            return existing, False

        epic = await self._repo.find_epic_by_title(project_id, CLOSE_OFF_EPIC_TITLE)
        if epic is None:
            existing_count = await self._repo.count_epics(project_id)
            color = EPIC_COLOR_PALETTE[existing_count % len(EPIC_COLOR_PALETTE)]
            number = await self._repo.next_epic_number(project_id)
            epic = await self._repo.create_epic(
                project_id=project_id,
                title=CLOSE_OFF_EPIC_TITLE,
                description=(
                    "Cross-cutting operational work — worktree teardown, "
                    "wave close-off, and other supervisor-owned chores."
                ),
                bounded_context="",
                context_description="",
                position=existing_count,
                color=color,
                number=number,
            )

        feature = await self._repo.find_feature_by_title(epic.id, CLOSE_OFF_FEATURE_TITLE)
        if feature is None:
            feature_number = await self._repo.next_feature_number(project_id)
            feature = await self._repo.create_feature(
                epic_id=epic.id,
                title=CLOSE_OFF_FEATURE_TITLE,
                description=(
                    "Each worktree gets a paired close-off task filed here "
                    "at creation time (T-246). The task tracks archiving "
                    "shutdown-artifacts, filing learnings, tearing down the "
                    "worktree, and committing the wave-fold directly to main."
                ),
                position=0,
                number=feature_number,
            )

        title, description = close_worktree_template(worktree_name)
        task_number = await self._repo.next_task_number(project_id)
        task = await self._repo.create_task(
            feature_id=feature.id,
            title=title,
            description=description,
            priority="normal",
            position=0,
            number=task_number,
            task_type="task",
        )
        # Assign to main agent so get_my_tasks surfaces it there; stamp the
        # close_off FK so idempotency holds on resume.
        fields: dict[str, object] = {"close_off_worktree_id": close_off_worktree_id}
        if main_agent_worktree_id is not None:
            fields["worktree_id"] = main_agent_worktree_id
        updated = await self._repo.update_task(task.id, **fields)
        assert updated is not None
        return updated, True

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
