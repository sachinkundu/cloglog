"""SQLAlchemy models for the Document bounded context."""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.database import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    doc_type: Mapped[str] = mapped_column(String(50), default="other")
    source_path: Mapped[str] = mapped_column(String(1000), default="")
    attached_to_type: Mapped[str] = mapped_column(String(50), default="")
    attached_to_id: Mapped[_uuid.UUID | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
