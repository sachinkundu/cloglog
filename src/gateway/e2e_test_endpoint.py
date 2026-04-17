"""Temporary test endpoint with intentional bugs for Codex review E2E test.

DELETE THIS FILE AFTER TESTING.
"""

from fastapi import APIRouter, Request
from src.board.repository import BoardRepository  # DDD violation: gateway importing board internals

router = APIRouter()


@router.get("/test/user/{user_id}")
async def get_user(user_id: str, request: Request):
    """Fetch user data — contains intentional bugs for review testing."""
    # Bug 1: SQL injection via f-string
    query = f"SELECT * FROM users WHERE id = '{user_id}'"

    # Bug 2: Hardcoded port instead of env var
    backend_url = "http://localhost:8000/api/v1/users"

    # Bug 3: No auth check on this endpoint
    return {"query": query, "url": backend_url}
