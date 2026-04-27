"""Pin tests: T-320.

init Step 2 must bootstrap a fresh project via a direct HTTP call to the backend,
not via mcp__cloglog__get_board (which cannot run before MCP is configured).

These tests assert:
1. Absence of mcp__cloglog__get_board in Step 2 (old broken path).
2. Presence of the curl-based project creation call in Step 2.
3. Presence of credential-writing steps (credentials file + project_id).
4. Presence of the restart instruction (two-phase protocol).
5. Default backend URL is http://localhost:8001, not http://localhost:8000.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INIT_SKILL = REPO_ROOT / "plugins/cloglog/skills/init/SKILL.md"


def _read() -> str:
    assert INIT_SKILL.exists(), f"{INIT_SKILL} missing — fix path or file was moved"
    return INIT_SKILL.read_text(encoding="utf-8")


def _step2_body(body: str) -> str:
    """Extract the text of Step 2 (between ## Step 2 and the next ## Step)."""
    lines = body.splitlines()
    in_step2 = False
    step2_lines: list[str] = []
    for line in lines:
        if line.startswith("## Step 2"):
            in_step2 = True
            step2_lines.append(line)
            continue
        if in_step2:
            if line.startswith("## Step ") and not line.startswith("## Step 2"):
                break
            step2_lines.append(line)
    assert step2_lines, "Could not locate ## Step 2 section in init SKILL.md"
    return "\n".join(step2_lines)


# ---------------------------------------------------------------------------
# Absence pins — old broken path must not return
# ---------------------------------------------------------------------------


def test_step2_does_not_call_mcp_get_board() -> None:
    """mcp__cloglog__get_board must not appear in Step 2.

    On a fresh project the MCP server is not yet configured, so this call
    would fail before any credentials are written.
    """
    step2 = _step2_body(_read())
    assert "mcp__cloglog__get_board" not in step2, (
        "Step 2 must not call mcp__cloglog__get_board — the MCP server is not "
        "configured on a fresh project. Use the direct HTTP bootstrap path instead."
    )


def test_skill_does_not_use_localhost_8000_as_default() -> None:
    """Default backend URL must be http://localhost:8001, not :8000.

    Per the portability audit (2026-04-27), port 8000 is reserved for
    cloglog's own dev server. Other projects talk to the prod backend on 8001.
    """
    body = _read()
    # Allow :8000 only in comments/notes that explicitly mention the dev-server
    # exception; disallow it as a bare default value.
    for line in body.splitlines():
        stripped = line.strip()
        if "localhost:8000" in stripped:
            # Fine if the line is a comment explaining the exception
            assert stripped.startswith("#") or stripped.startswith(">"), (
                f"init SKILL.md references localhost:8000 outside a comment/note:\n"
                f"  {line!r}\n"
                "The default backend URL must be http://localhost:8001. "
                "Port 8000 is cloglog's own dev server only."
            )


# ---------------------------------------------------------------------------
# Presence pins — new bootstrap path must exist in Step 2
# ---------------------------------------------------------------------------


def test_step2_uses_curl_to_create_project() -> None:
    """Step 2 must call the backend via curl to create the project."""
    step2 = _step2_body(_read())
    assert "curl" in step2, (
        "Step 2 must create the project via a direct curl call to "
        "POST /api/v1/board/projects — not via MCP tools."
    )


def test_step2_posts_to_projects_endpoint() -> None:
    """Step 2 must POST to /api/v1/board/projects."""
    step2 = _step2_body(_read())
    assert "/api/v1/board/projects" in step2, (
        "Step 2 must POST to /api/v1/board/projects to create the project "
        "without requiring pre-existing MCP credentials."
    )


def test_step2_uses_dashboard_key_auth() -> None:
    """Step 2 must authenticate using the X-Dashboard-Key header."""
    step2 = _step2_body(_read())
    assert "X-Dashboard-Key" in step2, (
        "Step 2 must pass the dashboard key via -H 'X-Dashboard-Key: ...' "
        "so the operator can bootstrap without an existing project API key."
    )


def test_step2_writes_credentials_file() -> None:
    """Step 2 must write ~/.cloglog/credentials with the new API key."""
    step2 = _step2_body(_read())
    assert "~/.cloglog/credentials" in step2, (
        "Step 2 must write the project API key to ~/.cloglog/credentials "
        "so the MCP server can load it on restart."
    )


def test_step2_writes_project_id_to_config() -> None:
    """Step 2 must persist the project_id to .cloglog/config.yaml."""
    step2 = _step2_body(_read())
    assert "project_id" in step2, (
        "Step 2 must write project_id to .cloglog/config.yaml "
        "so subsequent init re-runs detect the existing project."
    )


def test_step2_requests_restart() -> None:
    """Step 2 must instruct the operator to restart Claude Code after Phase 2."""
    step2 = _step2_body(_read())
    restart_mentioned = "restart" in step2.lower()
    assert restart_mentioned, (
        "Step 2 must tell the operator to restart Claude Code after writing "
        "credentials — the MCP server reads the API key only at startup."
    )


def test_step2_detects_existing_credentials() -> None:
    """Step 2 must check for existing ~/.cloglog/credentials to skip Phase 2 on re-runs."""
    step2 = _step2_body(_read())
    assert "~/.cloglog/credentials" in step2, (
        "Step 2 must check for an existing ~/.cloglog/credentials file to "
        "detect that the project was already bootstrapped and skip Phase 2."
    )
