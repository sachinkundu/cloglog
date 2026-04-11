"""Database queries for the Agent bounded context."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.models import AgentMessage, Session, Worktree


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
        """Delete worktree and all associated sessions and messages."""
        messages = (
            (
                await self._session.execute(
                    select(AgentMessage).where(AgentMessage.worktree_id == worktree_id)
                )
            )
            .scalars()
            .all()
        )
        for msg in messages:
            await self._session.delete(msg)

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

    # --- Messages ---

    async def queue_message(self, worktree_id: UUID, message: str, sender: str) -> AgentMessage:
        msg = AgentMessage(worktree_id=worktree_id, message=message, sender=sender)
        self._session.add(msg)
        await self._session.commit()
        await self._session.refresh(msg)
        return msg

    async def drain_messages(self, worktree_id: UUID) -> list[AgentMessage]:
        """Fetch and mark delivered all pending messages for a worktree."""
        result = await self._session.execute(
            select(AgentMessage)
            .where(
                AgentMessage.worktree_id == worktree_id,
                AgentMessage.delivered == False,  # noqa: E712
            )
            .order_by(AgentMessage.created_at)
        )
        messages = list(result.scalars().all())
        now = datetime.now(UTC)
        for msg in messages:
            msg.delivered = True
            msg.delivered_at = now
        await self._session.commit()
        return messages
