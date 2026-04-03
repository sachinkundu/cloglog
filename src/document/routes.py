"""FastAPI routes for the Document bounded context."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.document.repository import DocumentRepository
from src.document.schemas import DocumentCreate, DocumentResponse
from src.document.services import DocumentService
from src.shared.database import get_session

router = APIRouter()


def _get_service(session: Annotated[AsyncSession, Depends(get_session)]) -> DocumentService:
    return DocumentService(DocumentRepository(session))


ServiceDep = Annotated[DocumentService, Depends(_get_service)]


@router.post("/documents", response_model=DocumentResponse, status_code=201)
async def create_document(body: DocumentCreate, service: ServiceDep) -> dict[str, object]:
    return await service.create_document(
        title=body.title,
        content=body.content,
        doc_type=body.doc_type,
        source_path=body.source_path,
        attached_to_type=body.attached_to_type,
        attached_to_id=body.attached_to_id,
    )


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: UUID, service: ServiceDep) -> dict[str, object]:
    doc = await service.get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(
    service: ServiceDep,
    attached_to_type: Annotated[str | None, Query()] = None,
    attached_to_id: Annotated[UUID | None, Query()] = None,
) -> list[dict[str, object]]:
    if attached_to_type and attached_to_id:
        return await service.get_documents_for_entity(attached_to_type, attached_to_id)
    docs = await service._repo.list_documents()
    return [DocumentResponse.model_validate(d).model_dump() for d in docs]
