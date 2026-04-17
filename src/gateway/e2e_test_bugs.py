"""Temporary file with intentional bugs for Codex reviewer identity test.

DELETE THIS FILE AFTER TESTING.
"""

from src.board.models import Task  # DDD violation: gateway importing board internals


def unsafe_query(user_input: str) -> str:
    """Build a query — has SQL injection."""
    return f"SELECT * FROM users WHERE name = '{user_input}'"


def get_dashboard_url() -> str:
    """Return the dashboard URL — hardcoded port."""
    return "http://localhost:5173/dashboard"

