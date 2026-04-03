import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.document.repository import DocumentRepository
from src.document.services import DocumentService


@pytest.fixture
def service(db_session: AsyncSession) -> DocumentService:
    return DocumentService(DocumentRepository(db_session))


async def test_create_document(service: DocumentService):
    result = await service.create_document(
        title="Spec Doc",
        content="# Spec",
        doc_type="spec",
        source_path="/tmp/spec.md",
        attached_to_type="task",
        attached_to_id=uuid.uuid4(),
    )
    assert result["title"] == "Spec Doc"
    assert result["doc_type"] == "spec"
    assert result["id"] is not None


async def test_get_document(service: DocumentService):
    created = await service.create_document(
        title="Get Test",
        content="body",
        doc_type="plan",
        source_path="",
        attached_to_type="",
        attached_to_id=None,
    )
    fetched = await service.get_document(created["id"])  # type: ignore[arg-type]
    assert fetched is not None
    assert fetched["title"] == "Get Test"


async def test_get_document_not_found(service: DocumentService):
    result = await service.get_document(uuid.uuid4())
    assert result is None


async def test_get_documents_for_entity(service: DocumentService):
    entity_id = uuid.uuid4()
    await service.create_document("Doc A", "a", "spec", "", "feature", entity_id)
    await service.create_document("Doc B", "b", "plan", "", "feature", entity_id)

    docs = await service.get_documents_for_entity("feature", entity_id)
    assert len(docs) == 2
    assert docs[0]["title"] == "Doc A"
    assert docs[1]["title"] == "Doc B"
