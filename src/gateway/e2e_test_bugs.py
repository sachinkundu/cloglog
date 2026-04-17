"""Temporary file for Codex reviewer identity test — round 2 fixes.

DELETE THIS FILE AFTER TESTING.
"""

import os


def safe_query(user_input: str) -> tuple[str, list[str]]:
    """Build a parameterized query — SQL injection fixed."""
    return "SELECT * FROM users WHERE name = $1", [user_input]


def get_dashboard_url() -> str:
    """Return the dashboard URL from config — no more hardcoded port."""
    port = os.environ.get("FRONTEND_PORT", "5173")
    return f"http://localhost:{port}/dashboard"
