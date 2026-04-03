"""API key authentication dependency for the Gateway context."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Project
from src.board.repository import BoardRepository
from src.board.services import BoardService
from src.shared.database import get_session

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_project(
    api_key: Annotated[str | None, Security(_api_key_header)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Project:
    """Validate API key and return the associated project."""
    if api_key is None:
        raise HTTPException(status_code=401, detail="Missing API key")

    service = BoardService(BoardRepository(session))
    project = await service.verify_api_key(api_key)
    if project is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return project


CurrentProject = Annotated[Project, Depends(get_current_project)]
