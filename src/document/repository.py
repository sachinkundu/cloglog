"""Database queries for the Document bounded context."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.document.models import Document


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_document(
        self,
        title: str,
        content: str,
        doc_type: str,
        source_path: str,
        attached_to_type: str,
        attached_to_id: UUID | None,
    ) -> Document:
        document = Document(
            title=title,
            content=content,
            doc_type=doc_type,
            source_path=source_path,
            attached_to_type=attached_to_type,
            attached_to_id=attached_to_id,
        )
        self._session.add(document)
        await self._session.commit()
        await self._session.refresh(document)
        return document

    async def get_document(self, document_id: UUID) -> Document | None:
        return await self._session.get(Document, document_id)

    async def list_documents(self) -> list[Document]:
        result = await self._session.execute(select(Document).order_by(Document.created_at))
        return list(result.scalars().all())

    async def get_documents_for_entity(
        self, attached_to_type: str, attached_to_id: UUID
    ) -> list[Document]:
        result = await self._session.execute(
            select(Document)
            .where(
                Document.attached_to_type == attached_to_type,
                Document.attached_to_id == attached_to_id,
            )
            .order_by(Document.created_at)
        )
        return list(result.scalars().all())
