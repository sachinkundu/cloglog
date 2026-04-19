"""Tests for the hybrid `CurrentMcpOrDashboard` auth dependency (F-11)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.gateway.auth import get_mcp_or_dashboard
from src.shared.config import settings


def _request(headers: dict[str, str]) -> MagicMock:
    req = MagicMock()
    req.headers = headers
    req.query_params = {}
    return req


@pytest.mark.asyncio
async def test_mcp_path_with_valid_service_key_passes() -> None:
    await get_mcp_or_dashboard(
        _request(
            {
                "Authorization": f"Bearer {settings.mcp_service_key}",
                "X-MCP-Request": "true",
            }
        )
    )


@pytest.mark.asyncio
async def test_mcp_path_with_wrong_service_key_rejected() -> None:
    with pytest.raises(HTTPException) as excinfo:
        await get_mcp_or_dashboard(
            _request(
                {
                    "Authorization": "Bearer garbage",
                    "X-MCP-Request": "true",
                }
            )
        )
    assert excinfo.value.status_code == 401
    assert "Invalid MCP service key" in excinfo.value.detail


@pytest.mark.asyncio
async def test_dashboard_path_with_valid_key_passes() -> None:
    await get_mcp_or_dashboard(_request({"X-Dashboard-Key": settings.dashboard_secret}))


@pytest.mark.asyncio
async def test_dashboard_path_with_wrong_key_rejected() -> None:
    with pytest.raises(HTTPException) as excinfo:
        await get_mcp_or_dashboard(_request({"X-Dashboard-Key": "wrong"}))
    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_no_credentials_rejected() -> None:
    with pytest.raises(HTTPException) as excinfo:
        await get_mcp_or_dashboard(_request({}))
    assert excinfo.value.status_code == 401
