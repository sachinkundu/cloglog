"""SQLAlchemy models for the Board bounded context."""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    repo_url: Mapped[str] = mapped_column(String(500), default="")
    api_key_hash: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    next_epic_num: Mapped[int] = mapped_column(default=1)
    next_feature_num: Mapped[int] = mapped_column(default=1)
    next_task_num: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    epics: Mapped[list[Epic]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Epic(Base):
    __tablename__ = "epics"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    bounded_context: Mapped[str] = mapped_column(String(100), default="")
    context_description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="planned")
    position: Mapped[int] = mapped_column(default=0)
    color: Mapped[str] = mapped_column(String(7), default="")
    number: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    project: Mapped[Project] = relationship(back_populates="epics")
    features: Mapped[list[Feature]] = relationship(
        back_populates="epic", cascade="all, delete-orphan"
    )


class Feature(Base):
    __tablename__ = "features"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    epic_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("epics.id"))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="planned")
    position: Mapped[int] = mapped_column(default=0)
    number: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    epic: Mapped[Epic] = relationship(back_populates="features")
    tasks: Mapped[list[Task]] = relationship(back_populates="feature", cascade="all, delete-orphan")
    dependencies: Mapped[list[Feature]] = relationship(
        secondary="feature_dependencies",
        primaryjoin="Feature.id == feature_dependencies.c.feature_id",
        secondaryjoin="Feature.id == feature_dependencies.c.depends_on_id",
        lazy="selectin",
    )
    dependents: Mapped[list[Feature]] = relationship(
        secondary="feature_dependencies",
        primaryjoin="Feature.id == feature_dependencies.c.depends_on_id",
        secondaryjoin="Feature.id == feature_dependencies.c.feature_id",
        lazy="selectin",
        viewonly=True,
    )


class FeatureDependency(Base):
    __tablename__ = "feature_dependencies"

    feature_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("features.id"), primary_key=True)
    depends_on_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("features.id"), primary_key=True)


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    task_id: Mapped[_uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_task_id: Mapped[_uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (
        CheckConstraint("task_id <> depends_on_task_id", name="ck_task_dep_no_self_loop"),
        Index("ix_task_dependencies_depends_on_task_id", "depends_on_task_id"),
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    feature_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("features.id"))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="backlog")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    task_type: Mapped[str] = mapped_column(String(20), default="task")
    model: Mapped[str | None] = mapped_column(String(100), default=None)
    pr_url: Mapped[str | None] = mapped_column(String(500), default=None)
    pr_head_sha: Mapped[str | None] = mapped_column(String(64), default=None)
    pr_merged: Mapped[bool] = mapped_column(default=False)
    artifact_path: Mapped[str | None] = mapped_column(String(1000), default=None)
    worktree_id: Mapped[_uuid.UUID | None] = mapped_column(default=None)
    close_off_worktree_id: Mapped[_uuid.UUID | None] = mapped_column(
        ForeignKey("worktrees.id", ondelete="SET NULL"), default=None, unique=True
    )
    position: Mapped[int] = mapped_column(default=0)
    number: Mapped[int] = mapped_column(default=0)
    archived: Mapped[bool] = mapped_column(default=False)
    retired: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    feature: Mapped[Feature] = relationship(back_populates="tasks")
    notes: Mapped[list[TaskNote]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskNote.created_at"
    )
    dependencies: Mapped[list[Task]] = relationship(
        secondary="task_dependencies",
        primaryjoin="Task.id == task_dependencies.c.task_id",
        secondaryjoin="Task.id == task_dependencies.c.depends_on_task_id",
        lazy="selectin",
    )
    dependents: Mapped[list[Task]] = relationship(
        secondary="task_dependencies",
        primaryjoin="Task.id == task_dependencies.c.depends_on_task_id",
        secondaryjoin="Task.id == task_dependencies.c.task_id",
        lazy="selectin",
        viewonly=True,
    )


class TaskNote(Base):
    __tablename__ = "task_notes"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    task_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    task: Mapped[Task] = relationship(back_populates="notes")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    task_title: Mapped[str] = mapped_column(String(500))
    task_number: Mapped[int] = mapped_column(default=0)
    read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
