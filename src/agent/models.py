"""SQLAlchemy models for the Agent bounded context."""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.database import Base


class Worktree(Base):
    """Persistent agent identity tied to a git worktree path on the host.

    Identity is determined by project_id + worktree_path.
    If a session registers with a known worktree path, it reconnects.
    """

    __tablename__ = "worktrees"
    __table_args__ = (UniqueConstraint("project_id", "worktree_path", name="uq_worktree_project"),)

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    worktree_path: Mapped[str] = mapped_column(String(500))
    branch_name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="offline")  # online, offline
    role: Mapped[str] = mapped_column(
        String(20), default="worktree", server_default="worktree"
    )  # main, worktree — used by the webhook resolver's tertiary fallback
    shutdown_requested: Mapped[bool] = mapped_column(default=False)
    current_task_id: Mapped[_uuid.UUID | None] = mapped_column(default=None)
    agent_token_hash: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    sessions: Mapped[list[Session]] = relationship(
        back_populates="worktree", cascade="all, delete-orphan"
    )


class Session(Base):
    """Tracks an individual agent session with heartbeat."""

    __tablename__ = "sessions"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    worktree_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("worktrees.id"))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_heartbeat: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, ended, timed_out
    metadata_: Mapped[str] = mapped_column("metadata", Text, default="{}")

    worktree: Mapped[Worktree] = relationship(back_populates="sessions")
