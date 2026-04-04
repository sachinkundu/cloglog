"""API key authentication dependency for the Gateway context."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Project
from src.board.repository import BoardRepository
from src.board.services import BoardService
from src.shared.database import get_session


async def get_current_project(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Project:
    """Validate API key from Authorization: Bearer <key> and return the associated project.

    Also sets request.state.project_id for downstream route handlers.
    """
    auth_header = request.headers.get("Authorization")
    api_key: str | None = None

    if auth_header and auth_header.startswith("Bearer "):
        api_key = auth_header[7:]

    # Also accept X-API-Key header as fallback
    if api_key is None:
        api_key = request.headers.get("X-API-Key")

    if api_key is None:
        raise HTTPException(status_code=401, detail="Missing API key")

    service = BoardService(BoardRepository(session))
    project = await service.verify_api_key(api_key)
    if project is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Set project_id on request state for agent routes
    request.state.project_id = project.id
    return project


CurrentProject = Annotated[Project, Depends(get_current_project)]
