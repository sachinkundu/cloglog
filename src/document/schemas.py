"""Pydantic schemas for the Document context API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.shared.text import NulSanitizedModel


class DocumentCreate(NulSanitizedModel):
    title: str = ""
    content: str = ""
    doc_type: str = "other"
    source_path: str = ""
    attached_to_type: str = ""
    attached_to_id: UUID | None = None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    content: str
    doc_type: str
    source_path: str
    attached_to_type: str
    attached_to_id: UUID | None
    created_at: datetime
