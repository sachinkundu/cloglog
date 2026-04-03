import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.document.repository import DocumentRepository


@pytest.fixture
def repo(db_session: AsyncSession) -> DocumentRepository:
    return DocumentRepository(db_session)


# --- Create ---


async def test_create_document(repo: DocumentRepository):
    doc = await repo.create_document(
        title="Design Spec",
        content="# Design\nSome content",
        doc_type="spec",
        source_path="/tmp/spec.md",
        attached_to_type="task",
        attached_to_id=uuid.uuid4(),
    )
    assert doc.title == "Design Spec"
    assert doc.content == "# Design\nSome content"
    assert doc.doc_type == "spec"
    assert doc.id is not None
    assert doc.created_at is not None


async def test_create_document_minimal(repo: DocumentRepository):
    doc = await repo.create_document(
        title="",
        content="",
        doc_type="other",
        source_path="",
        attached_to_type="",
        attached_to_id=None,
    )
    assert doc.id is not None
    assert doc.doc_type == "other"


# --- Get ---


async def test_get_document(repo: DocumentRepository):
    doc = await repo.create_document(
        title="Test Doc",
        content="body",
        doc_type="plan",
        source_path="",
        attached_to_type="",
        attached_to_id=None,
    )
    fetched = await repo.get_document(doc.id)
    assert fetched is not None
    assert fetched.title == "Test Doc"


async def test_get_document_not_found(repo: DocumentRepository):
    result = await repo.get_document(uuid.uuid4())
    assert result is None


# --- List ---


async def test_list_documents(repo: DocumentRepository):
    await repo.create_document("Doc 1", "a", "spec", "", "", None)
    await repo.create_document("Doc 2", "b", "plan", "", "", None)
    docs = await repo.list_documents()
    assert len(docs) >= 2


# --- Filter by entity ---


async def test_get_documents_for_entity(repo: DocumentRepository):
    entity_id = uuid.uuid4()
    await repo.create_document("Attached", "content", "spec", "", "task", entity_id)
    await repo.create_document("Unrelated", "other", "plan", "", "epic", uuid.uuid4())

    docs = await repo.get_documents_for_entity("task", entity_id)
    assert len(docs) == 1
    assert docs[0].title == "Attached"


async def test_get_documents_for_entity_empty(repo: DocumentRepository):
    docs = await repo.get_documents_for_entity("task", uuid.uuid4())
    assert docs == []
