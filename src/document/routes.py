"""FastAPI routes for the Document bounded context."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.repository import BoardRepository
from src.document.repository import DocumentRepository
from src.document.schemas import DocumentCreate, DocumentResponse
from src.document.services import DocumentService
from src.shared.database import get_session
from src.shared.events import Event, EventType, event_bus

router = APIRouter()


def _get_service(session: Annotated[AsyncSession, Depends(get_session)]) -> DocumentService:
    return DocumentService(DocumentRepository(session))


ServiceDep = Annotated[DocumentService, Depends(_get_service)]


async def _resolve_project_id(
    attached_to_type: str, attached_to_id: UUID, board_repo: BoardRepository
) -> UUID | None:
    """Walk up the entity chain to find the project_id."""
    if attached_to_type == "epic":
        epic = await board_repo.get_epic(attached_to_id)
        return epic.project_id if epic else None
    if attached_to_type == "feature":
        feature = await board_repo.get_feature(attached_to_id)
        if feature is None:
            return None
        epic = await board_repo.get_epic(feature.epic_id)
        return epic.project_id if epic else None
    if attached_to_type == "task":
        task = await board_repo.get_task(attached_to_id)
        if task is None:
            return None
        feature = await board_repo.get_feature(task.feature_id)
        if feature is None:
            return None
        epic = await board_repo.get_epic(feature.epic_id)
        return epic.project_id if epic else None
    return None


@router.post("/documents", response_model=DocumentResponse, status_code=201)
async def create_document(
    body: DocumentCreate,
    service: ServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    result = await service.create_document(
        title=body.title,
        content=body.content,
        doc_type=body.doc_type,
        source_path=body.source_path,
        attached_to_type=body.attached_to_type,
        attached_to_id=body.attached_to_id,
    )
    if body.attached_to_id is not None:
        board_repo = BoardRepository(session)
        project_id = await _resolve_project_id(
            body.attached_to_type, body.attached_to_id, board_repo
        )
        if project_id is not None:
            await event_bus.publish(
                Event(
                    type=EventType.DOCUMENT_ATTACHED,
                    project_id=project_id,
                    data={
                        "document_id": str(result["id"]),
                        "attached_to_type": body.attached_to_type,
                        "attached_to_id": str(body.attached_to_id),
                    },
                )
            )
    return result


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
