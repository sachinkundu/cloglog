"""Regression guard: T-214.

The committed `.mcp.json` (and any per-worktree `.mcp.json` written by
`on-worktree-create.sh`) MUST NOT carry the project API key. Any process
inside a worktree can read these files; keeping the key in them defeats the
"agents talk to the backend only via MCP" rule that the prefer-mcp.sh hook
enforces on the curl side.

Authoritative key sources are:

  1. ``CLOGLOG_API_KEY`` in the launcher's environment, OR
  2. ``~/.cloglog/credentials``  (mode 0600).

See ``mcp-server/src/credentials.ts`` and ``docs/setup-credentials.md``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MCP_JSON = REPO_ROOT / ".mcp.json"


def _cloglog_env() -> dict[str, str]:
    if not MCP_JSON.exists():
        pytest.skip(".mcp.json not present in this checkout")
    data = json.loads(MCP_JSON.read_text())
    servers = data.get("mcpServers", {})
    cloglog = servers.get("cloglog")
    assert cloglog is not None, ".mcp.json has no `cloglog` server entry"
    return dict(cloglog.get("env") or {})


def test_mcp_json_does_not_contain_api_key_field() -> None:
    env = _cloglog_env()
    assert "CLOGLOG_API_KEY" not in env, (
        "CLOGLOG_API_KEY must not appear in .mcp.json — see docs/setup-credentials.md"
    )


def test_mcp_json_text_does_not_contain_api_key_value() -> None:
    """Even with the field removed, accidentally pasting a key elsewhere
    (a comment, a different env name) is forbidden. A 64-hex token at any
    position fails the guard."""
    if not MCP_JSON.exists():
        pytest.skip(".mcp.json not present in this checkout")
    body = MCP_JSON.read_text()
    assert not re.search(r"\b[0-9a-f]{64}\b", body), (
        "A 64-char hex value (project API key shape) is present in .mcp.json. "
        "Remove it; credentials live in env or ~/.cloglog/credentials."
    )


def test_mcp_json_keeps_url_and_does_not_add_other_secrets() -> None:
    """Sanity: the file still configures the MCP server, just without secrets.
    The only env var we expect is ``CLOGLOG_URL``; anything else needs review."""
    env = _cloglog_env()
    assert "CLOGLOG_URL" in env, ".mcp.json must still configure CLOGLOG_URL"
    extras = set(env) - {"CLOGLOG_URL"}
    assert not extras, (
        f"Unexpected env keys in .mcp.json: {sorted(extras)}. "
        "Move secrets to ~/.cloglog/credentials."
    )
