"""API key authentication dependencies for the Gateway context.

Credential types:
- CurrentProject: validates project API key (for agent registration)
- CurrentAgent: validates per-agent token + worktree_id binding
- CurrentMcpService: validates MCP service key (for board/document routes)
- SupervisorAuth: accepts MCP service key, project API key (project must own
  the target worktree), or the target agent's own token — used for supervisor
  actions on a target worktree in the URL path (e.g. assign-task)
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


async def get_supervisor_auth(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Worktree:
    """Authorize a supervisor action on the target worktree in the URL.

    Accepts any of:
    1. MCP service key (X-MCP-Request + Bearer mcp_service_key)
    2. Project API key (Bearer api_key) — must own the target worktree
    3. Target agent's own token (Bearer agent_token matching URL worktree_id)

    Returns the target Worktree resolved from the URL path. Credential
    validation runs before worktree lookup to avoid leaking existence of
    worktree IDs to unauthenticated callers.
    """
    worktree_id_param = request.path_params.get("worktree_id")
    if worktree_id_param is None:
        raise HTTPException(status_code=400, detail="Missing worktree_id in URL")
    target_id = UUID(worktree_id_param)

    token = _extract_bearer_token(request)
    mcp_header = request.headers.get("X-MCP-Request")
    agent_repo = AgentRepository(session)

    # Path 1: MCP service key
    if mcp_header:
        if not token or not hmac.compare_digest(token, settings.mcp_service_key):
            raise HTTPException(status_code=401, detail="Invalid MCP service key")
        worktree = await agent_repo.get_worktree(target_id)
        if worktree is None:
            raise HTTPException(status_code=404, detail="Worktree not found")
        request.state.worktree = worktree
        request.state.project_id = worktree.project_id
        return worktree

    if token is None:
        raise HTTPException(status_code=401, detail="Missing credentials")

    # Path 2: Project API key — must own the target worktree
    board_service = BoardService(BoardRepository(session))
    project = await board_service.verify_api_key(token)
    if project is not None:
        worktree = await agent_repo.get_worktree(target_id)
        if worktree is None:
            raise HTTPException(status_code=404, detail="Worktree not found")
        if worktree.project_id != project.id:
            raise HTTPException(
                status_code=403,
                detail="Worktree does not belong to this project",
            )
        request.state.worktree = worktree
        request.state.project_id = project.id
        return worktree

    # Path 3: Target agent's own token
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    token_worktree = await agent_repo.get_worktree_by_token_hash(token_hash)
    if token_worktree is not None and token_worktree.id == target_id:
        request.state.worktree = token_worktree
        request.state.project_id = token_worktree.project_id
        return token_worktree

    raise HTTPException(status_code=401, detail="Invalid credentials")


SupervisorAuth = Annotated[Worktree, Depends(get_supervisor_auth)]
