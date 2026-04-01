"""Protocols exposed by the Document context to other contexts."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class DocumentService(Protocol):
    """Used by Gateway to query documents."""

    async def get_documents_for_entity(
        self, attached_to_type: str, attached_to_id: UUID
    ) -> list[dict[str, object]]: ...

    async def get_document(self, document_id: UUID) -> dict[str, object] | None: ...
