"""Database queries for the Agent bounded context."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.models import Session, Worktree


class AgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Worktree ---

    async def upsert_worktree(
        self, project_id: UUID, worktree_path: str, branch_name: str
    ) -> tuple[Worktree, bool]:
        """Find or create a worktree. Returns (worktree, is_new)."""
        result = await self._session.execute(
            select(Worktree).where(
                Worktree.project_id == project_id,
                Worktree.worktree_path == worktree_path,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.status = "online"
            # Only overwrite branch_name if the caller actually supplied one.
            # A transient empty value (e.g. MCP probe failed briefly) must not
            # wipe a previously populated name — that would re-open the
            # empty-branch data trap the webhook resolver guards against.
            if branch_name:
                existing.branch_name = branch_name
            await self._session.commit()
            await self._session.refresh(existing)
            return existing, False

        worktree = Worktree(
            project_id=project_id,
            worktree_path=worktree_path,
            branch_name=branch_name,
            status="online",
        )
        self._session.add(worktree)
        await self._session.commit()
        await self._session.refresh(worktree)
        return worktree, True

    async def get_worktree(self, worktree_id: UUID) -> Worktree | None:
        return await self._session.get(Worktree, worktree_id)

    async def get_worktrees_for_project(self, project_id: UUID) -> list[Worktree]:
        result = await self._session.execute(
            select(Worktree).where(Worktree.project_id == project_id).order_by(Worktree.created_at)
        )
        return list(result.scalars().all())

    async def get_latest_heartbeat(self, worktree_id: UUID) -> datetime | None:
        """Get the most recent heartbeat for a worktree's active session."""
        result = await self._session.execute(
            select(Session.last_heartbeat)
            .where(Session.worktree_id == worktree_id)
            .order_by(Session.last_heartbeat.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def set_worktree_offline(self, worktree_id: UUID) -> None:
        await self._session.execute(
            update(Worktree).where(Worktree.id == worktree_id).values(status="offline")
        )
        await self._session.commit()

    async def set_worktree_current_task(self, worktree_id: UUID, task_id: UUID | None) -> None:
        await self._session.execute(
            update(Worktree).where(Worktree.id == worktree_id).values(current_task_id=task_id)
        )
        await self._session.commit()

    async def request_shutdown(self, worktree_id: UUID) -> None:
        await self._session.execute(
            update(Worktree).where(Worktree.id == worktree_id).values(shutdown_requested=True)
        )
        await self._session.commit()

    async def get_worktree_by_token_hash(self, token_hash: str) -> Worktree | None:
        result = await self._session.execute(
            select(Worktree).where(Worktree.agent_token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def set_agent_token_hash(self, worktree_id: UUID, token_hash: str) -> None:
        await self._session.execute(
            update(Worktree).where(Worktree.id == worktree_id).values(agent_token_hash=token_hash)
        )
        await self._session.commit()

    async def get_worktree_by_branch(self, project_id: UUID, branch_name: str) -> Worktree | None:
        """Find an online worktree by its branch name within a project.

        Returns ``None`` when ``branch_name`` is empty — a historical data bug
        left many rows with ``branch_name=''`` online at once, and a literal
        equality match on the empty string would hit every one of them and
        raise ``MultipleResultsFound``. The resolver short-circuits upstream
        too; this guard protects any other caller from the same trap.
        """
        if not branch_name:
            return None
        result = await self._session.execute(
            select(Worktree).where(
                Worktree.project_id == project_id,
                Worktree.branch_name == branch_name,
                Worktree.status == "online",
            )
        )
        return result.scalar_one_or_none()

    async def find_worktree_by_branch_any_status(
        self, project_id: UUID, branch_name: str
    ) -> Worktree | None:
        """Find a worktree by branch within a project, regardless of ``status``.

        Unlike ``get_worktree_by_branch`` (which filters to ``status='online'``
        because it is used to route messages to a live agent), this query is
        for callers that only need the worktree's filesystem path — e.g. the
        T-278 per-PR review-root resolver. A recently-offline worktree row
        still points at a valid checkout on disk, and that is a far better
        codex review root than prod's ``main``.

        Returns ``None`` when ``branch_name`` is empty or when more than one
        row matches — the empty-branch data trap (many rows with
        ``branch_name=''``) would otherwise surface as
        ``MultipleResultsFound``.
        """
        if not branch_name:
            return None
        result = await self._session.execute(
            select(Worktree).where(
                Worktree.project_id == project_id,
                Worktree.branch_name == branch_name,
            )
        )
        rows = list(result.scalars().all())
        if len(rows) != 1:
            return None
        return rows[0]

    async def get_offline_worktrees(self, project_id: UUID) -> list[Worktree]:
        result = await self._session.execute(
            select(Worktree).where(
                Worktree.project_id == project_id,
                Worktree.status == "offline",
            )
        )
        return list(result.scalars().all())

    async def get_worktree_by_path(self, project_id: UUID, worktree_path: str) -> Worktree | None:
        result = await self._session.execute(
            select(Worktree).where(
                Worktree.project_id == project_id,
                Worktree.worktree_path == worktree_path,
            )
        )
        return result.scalar_one_or_none()

    async def delete_worktree(self, worktree_id: UUID) -> None:
        """Delete worktree and all associated sessions."""
        sessions = (
            (await self._session.execute(select(Session).where(Session.worktree_id == worktree_id)))
            .scalars()
            .all()
        )
        for s in sessions:
            await self._session.delete(s)

        worktree = await self._session.get(Worktree, worktree_id)
        if worktree is not None:
            await self._session.delete(worktree)

        await self._session.commit()

    # --- Session ---

    async def create_session(self, worktree_id: UUID) -> Session:
        session = Session(worktree_id=worktree_id)
        self._session.add(session)
        await self._session.commit()
        await self._session.refresh(session)
        return session

    async def get_active_session(self, worktree_id: UUID) -> Session | None:
        result = await self._session.execute(
            select(Session).where(
                Session.worktree_id == worktree_id,
                Session.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def update_heartbeat(self, session_id: UUID) -> Session | None:
        session = await self._session.get(Session, session_id)
        if session is None:
            return None
        session.last_heartbeat = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(session)
        return session

    async def end_session(self, session_id: UUID, status: str = "ended") -> None:
        session = await self._session.get(Session, session_id)
        if session is not None:
            session.status = status
            session.ended_at = datetime.now(UTC)
            await self._session.commit()

    async def get_timed_out_sessions(self, cutoff: datetime) -> list[Session]:
        """Find active sessions whose last heartbeat is before the cutoff."""
        result = await self._session.execute(
            select(Session).where(
                Session.status == "active",
                Session.last_heartbeat < cutoff,
            )
        )
        return list(result.scalars().all())
