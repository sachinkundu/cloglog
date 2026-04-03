"""E2E tests for the document flow.

Covers: document creation, retrieval by ID, listing,
and filtering by attached_to_type / attached_to_id.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _unique_name(prefix: str = "doc-e2e") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ── Create and read ──────────────────────────────────────────


async def test_create_document(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/documents",
        json={
            "title": "Design Doc",
            "content": "# Architecture\nSome content here.",
            "doc_type": "design",
            "source_path": "docs/design.md",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Design Doc"
    assert data["doc_type"] == "design"
    assert "id" in data
    assert "created_at" in data


async def test_get_document_by_id(client: AsyncClient) -> None:
    created = (
        await client.post(
            "/api/v1/documents",
            json={"title": "Lookup Doc", "content": "body text"},
        )
    ).json()

    resp = await client.get(f"/api/v1/documents/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Lookup Doc"
    assert resp.json()["content"] == "body text"


async def test_list_documents(client: AsyncClient) -> None:
    await client.post("/api/v1/documents", json={"title": "List Doc A", "content": "a"})
    await client.post("/api/v1/documents", json={"title": "List Doc B", "content": "b"})

    resp = await client.get("/api/v1/documents")
    assert resp.status_code == 200
    titles = [d["title"] for d in resp.json()]
    assert "List Doc A" in titles
    assert "List Doc B" in titles


# ── Attachment filtering ─────────────────────────────────────


async def test_filter_documents_by_attachment(client: AsyncClient) -> None:
    task_id = str(uuid.uuid4())

    # Create document attached to a task
    await client.post(
        "/api/v1/documents",
        json={
            "title": "Task Log",
            "content": "log content",
            "attached_to_type": "task",
            "attached_to_id": task_id,
        },
    )
    # Create unattached document
    await client.post(
        "/api/v1/documents",
        json={"title": "Unattached", "content": "misc"},
    )

    # Filter by attachment
    resp = await client.get(
        "/api/v1/documents",
        params={"attached_to_type": "task", "attached_to_id": task_id},
    )
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) >= 1
    assert all(d["attached_to_id"] == task_id for d in docs)


async def test_document_with_all_fields(client: AsyncClient) -> None:
    project_id = str(uuid.uuid4())

    resp = await client.post(
        "/api/v1/documents",
        json={
            "title": "Full Doc",
            "content": "Complete document with all fields.",
            "doc_type": "plan",
            "source_path": "docs/plans/phase1.md",
            "attached_to_type": "project",
            "attached_to_id": project_id,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["doc_type"] == "plan"
    assert data["source_path"] == "docs/plans/phase1.md"
    assert data["attached_to_type"] == "project"
    assert data["attached_to_id"] == project_id
