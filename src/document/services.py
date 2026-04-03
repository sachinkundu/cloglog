"""Business logic for the Document bounded context."""

from __future__ import annotations

from uuid import UUID

from src.document.repository import DocumentRepository


class DocumentService:
    def __init__(self, repo: DocumentRepository) -> None:
        self._repo = repo

    async def create_document(
        self,
        title: str,
        content: str,
        doc_type: str,
        source_path: str,
        attached_to_type: str,
        attached_to_id: UUID | None,
    ) -> dict[str, object]:
        doc = await self._repo.create_document(
            title=title,
            content=content,
            doc_type=doc_type,
            source_path=source_path,
            attached_to_type=attached_to_type,
            attached_to_id=attached_to_id,
        )
        return self._to_dict(doc)

    async def get_document(self, document_id: UUID) -> dict[str, object] | None:
        doc = await self._repo.get_document(document_id)
        if doc is None:
            return None
        return self._to_dict(doc)

    async def get_documents_for_entity(
        self, attached_to_type: str, attached_to_id: UUID
    ) -> list[dict[str, object]]:
        docs = await self._repo.get_documents_for_entity(attached_to_type, attached_to_id)
        return [self._to_dict(d) for d in docs]

    @staticmethod
    def _to_dict(doc: object) -> dict[str, object]:
        from src.document.models import Document

        assert isinstance(doc, Document)
        return {
            "id": doc.id,
            "title": doc.title,
            "content": doc.content,
            "doc_type": doc.doc_type,
            "source_path": doc.source_path,
            "attached_to_type": doc.attached_to_type,
            "attached_to_id": doc.attached_to_id,
            "created_at": doc.created_at,
        }
