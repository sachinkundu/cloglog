"""E2E tests for document event emission."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


async def test_create_document_emits_event(client: AsyncClient):
    """Attaching a document emits a DOCUMENT_ATTACHED event."""
    project = (await client.post("/api/v1/projects", json={"name": "doc-event-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()

    with patch("src.document.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.post(
            "/api/v1/documents",
            json={
                "title": "Spec",
                "content": "# Spec content",
                "doc_type": "spec",
                "source_path": "",
                "attached_to_type": "feature",
                "attached_to_id": feature["id"],
            },
        )
        assert resp.status_code == 201
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "document_attached"
        assert str(event.project_id) == project["id"]
