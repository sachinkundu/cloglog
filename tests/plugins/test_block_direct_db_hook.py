"""T-417 pin: ``block-direct-db.sh`` MUST hard-block any Bash command
that runs ``psql`` (or ``docker exec ... psql``) against the cloglog
dev or prod database.

The "No psql for board lookups" feedback memory keeps getting violated
because read-only SELECTs feel safe, but they bypass the audit log,
hit the dev DB directly, and normalise drift around MCP. Memory alone
hasn't held — this hook turns the rule into an enforced invariant.

Escape hatch: inline ``ALLOW_RAW_DB=1`` env prefix releases the call
for the rare case where a schema audit genuinely cannot be answered
through MCP.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "plugins/cloglog/hooks/block-direct-db.sh"


def _run_hook(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )


def test_hook_exists_and_executable() -> None:
    assert HOOK.exists(), f"{HOOK} missing"
    assert HOOK.stat().st_mode & 0o111, f"{HOOK} must be executable"


def test_hook_blocks_psql_dev_select() -> None:
    """The 2026-05-04 incident command shape — a read-only SELECT against
    cloglog_dev — MUST be rejected. Read-only is not a free pass."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": 'psql -h 127.0.0.1 -U cloglog -d cloglog_dev -c "select 1"',
        },
    }
    result = _run_hook(payload)
    assert result.returncode != 0, (
        "block-direct-db.sh must reject psql against cloglog_dev. "
        "Read-only SELECTs are exactly the shape that re-introduced "
        "the drift the feedback memory was meant to prevent."
    )
    err = result.stderr.lower()
    assert "blocked" in err and "mcp" in err, (
        "Block message must name MCP alternatives so the agent can "
        "self-correct without operator help."
    )


def test_hook_blocks_psql_prod() -> None:
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": 'psql -h 127.0.0.1 -U cloglog -d cloglog_prod -c "select 1"',
        },
    }
    result = _run_hook(payload)
    assert result.returncode != 0


def test_hook_blocks_docker_exec_psql() -> None:
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "docker exec -it pg psql -U cloglog -d cloglog_dev -c 'select 1'",
        },
    }
    result = _run_hook(payload)
    assert result.returncode != 0


def test_hook_allows_with_allow_raw_db_env_prefix() -> None:
    """Inline ``ALLOW_RAW_DB=1`` releases the call — the rare schema
    audit escape hatch."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": 'ALLOW_RAW_DB=1 psql -h 127.0.0.1 -U cloglog -d cloglog_dev -c "select 1"',
        },
    }
    result = _run_hook(payload)
    assert result.returncode == 0, (
        "ALLOW_RAW_DB=1 inline env prefix must release the call. "
        "Without an escape hatch, real schema audits are impossible."
    )


def test_hook_allows_unrelated_psql() -> None:
    """psql against a non-cloglog database is out of scope — the rule
    is specifically about the cloglog dev/prod DBs."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "psql -d some_other_app -c 'select 1'"},
    }
    result = _run_hook(payload)
    assert result.returncode == 0


def test_hook_allows_unrelated_bash() -> None:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la"},
    }
    result = _run_hook(payload)
    assert result.returncode == 0


def test_hook_passes_through_non_bash_tools() -> None:
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": "/tmp/foo", "old_string": "a", "new_string": "b"},
    }
    result = _run_hook(payload)
    assert result.returncode == 0


def test_hook_registered_in_plugin_settings() -> None:
    """Without registration the hook script is dead weight — pin the
    PreToolUse / Bash matcher entry so a future settings refactor
    can't silently drop it."""
    settings = json.loads((REPO_ROOT / "plugins/cloglog/settings.json").read_text(encoding="utf-8"))
    bash_pre = [
        entry for entry in settings["hooks"]["PreToolUse"] if entry.get("matcher") == "Bash"
    ]
    assert bash_pre, "Plugin settings must have a PreToolUse Bash matcher"
    commands = [h["command"] for entry in bash_pre for h in entry["hooks"]]
    assert any("block-direct-db.sh" in c for c in commands), (
        "block-direct-db.sh must be registered under PreToolUse/Bash "
        "in plugins/cloglog/settings.json — without registration the "
        "guard never runs."
    )
