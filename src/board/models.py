"""SQLAlchemy models for the Board bounded context."""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, text
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


class FeatureDependency(Base):
    __tablename__ = "feature_dependencies"

    feature_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("features.id"), primary_key=True)
    depends_on_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("features.id"), primary_key=True)


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
    worktree_id: Mapped[_uuid.UUID | None] = mapped_column(default=None)
    position: Mapped[int] = mapped_column(default=0)
    number: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    feature: Mapped[Feature] = relationship(back_populates="tasks")
