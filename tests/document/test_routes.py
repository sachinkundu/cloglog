import uuid

from httpx import AsyncClient


async def test_create_document(client: AsyncClient):
    resp = await client.post(
        "/api/v1/documents",
        json={
            "title": "My Spec",
            "content": "# Spec content",
            "doc_type": "spec",
            "source_path": "/tmp/spec.md",
            "attached_to_type": "task",
            "attached_to_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "My Spec"
    assert data["doc_type"] == "spec"
    assert "id" in data
    assert "created_at" in data


async def test_create_document_minimal(client: AsyncClient):
    resp = await client.post("/api/v1/documents", json={})
    assert resp.status_code == 201
    data = resp.json()
    assert data["doc_type"] == "other"
    assert data["title"] == ""


async def test_get_document(client: AsyncClient):
    create_resp = await client.post(
        "/api/v1/documents",
        json={"title": "Get Test", "content": "body"},
    )
    doc_id = create_resp.json()["id"]
    resp = await client.get(f"/api/v1/documents/{doc_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Get Test"


async def test_get_document_not_found(client: AsyncClient):
    resp = await client.get(f"/api/v1/documents/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_list_documents(client: AsyncClient):
    await client.post("/api/v1/documents", json={"title": "Doc 1"})
    await client.post("/api/v1/documents", json={"title": "Doc 2"})
    resp = await client.get("/api/v1/documents")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


async def test_list_documents_filtered_by_entity(client: AsyncClient):
    entity_id = str(uuid.uuid4())
    await client.post(
        "/api/v1/documents",
        json={"title": "Attached", "attached_to_type": "epic", "attached_to_id": entity_id},
    )
    await client.post(
        "/api/v1/documents",
        json={"title": "Other", "attached_to_type": "task", "attached_to_id": str(uuid.uuid4())},
    )
    resp = await client.get(
        "/api/v1/documents",
        params={"attached_to_type": "epic", "attached_to_id": entity_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Attached"
