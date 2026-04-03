"""FastAPI routes for the Gateway bounded context."""

from __future__ import annotations

from fastapi import APIRouter

from src.board.schemas import ProjectResponse
from src.gateway.auth import CurrentProject

router = APIRouter(prefix="/gateway", tags=["gateway"])


@router.get("/me", response_model=ProjectResponse)
async def get_current_project_info(project: CurrentProject) -> ProjectResponse:
    """Return the project associated with the current API key."""
    return ProjectResponse.model_validate(project)
