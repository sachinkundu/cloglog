"""Tests for ProjectCreate field validation — specifically the description validator."""

from httpx import AsyncClient


async def test_create_project_empty_description_returns_422(client: AsyncClient):
    """Explicitly passing description='' must be rejected with 422."""
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "empty-desc-project", "description": ""},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    # At least one validation error must mention the description field
    assert any("description" in str(err.get("loc", "")) for err in detail), (
        f"Expected 'description' in error locations, got: {detail}"
    )


async def test_create_project_valid_description_returns_201(client: AsyncClient):
    """A non-empty description string is accepted and stored."""
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "valid-desc-project", "description": "A real description"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["description"] == "A real description"


async def test_create_project_omitted_description_returns_201(client: AsyncClient):
    """Omitting description entirely uses the default and must not trigger the validator."""
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "no-desc-project"},
    )
    assert resp.status_code == 201
    data = resp.json()
    # Default is empty string and is stored as-is
    assert data["description"] == ""


async def test_create_project_whitespace_description_returns_201(client: AsyncClient):
    """A whitespace-only description is not the same as '' — it must be accepted."""
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "whitespace-desc-project", "description": "   "},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["description"] == "   "
