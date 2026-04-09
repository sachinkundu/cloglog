"""API key authentication dependencies for the Gateway context.

Three credential types:
- CurrentProject: validates project API key (for agent registration)
- CurrentAgent: validates per-agent token + worktree_id binding
- CurrentMcpService: validates MCP service key (for board/document routes)
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.models import Worktree
from src.agent.repository import AgentRepository
from src.board.models import Project
from src.board.repository import BoardRepository
from src.board.services import BoardService
from src.shared.config import settings
from src.shared.database import get_session


def _extract_bearer_token(request: Request) -> str | None:
    """Extract Bearer token from Authorization header or X-API-Key fallback."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.headers.get("X-API-Key")


async def get_current_project(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Project:
    """Validate API key from Authorization: Bearer <key> and return the associated project.

    Also sets request.state.project_id for downstream route handlers.
    """
    api_key = _extract_bearer_token(request)

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


async def get_current_agent(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Worktree:
    """Validate agent token and return the authenticated Worktree.

    Also verifies that the token matches the worktree_id in the URL path.
    """
    token = _extract_bearer_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Missing agent token")

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    repo = AgentRepository(session)
    worktree = await repo.get_worktree_by_token_hash(token_hash)
    if worktree is None:
        raise HTTPException(status_code=401, detail="Invalid agent token")

    # Verify token matches the worktree_id in the URL
    worktree_id_param = request.path_params.get("worktree_id")
    if worktree_id_param and UUID(worktree_id_param) != worktree.id:
        raise HTTPException(
            status_code=403,
            detail="Agent token does not match worktree_id in URL",
        )

    request.state.worktree = worktree
    request.state.project_id = worktree.project_id
    return worktree


CurrentAgent = Annotated[Worktree, Depends(get_current_agent)]


async def get_mcp_service(request: Request) -> None:
    """Validate MCP service key. No DB lookup needed."""
    mcp_header = request.headers.get("X-MCP-Request")

    if not mcp_header:
        raise HTTPException(status_code=403, detail="Not an MCP request")

    token = _extract_bearer_token(request) or ""
    if not hmac.compare_digest(token, settings.mcp_service_key):
        raise HTTPException(status_code=401, detail="Invalid MCP service key")


CurrentMcpService = Annotated[None, Depends(get_mcp_service)]
