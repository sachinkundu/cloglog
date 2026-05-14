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


def test_hook_blocks_docker_compose_exec_psql() -> None:
    """T-417 codex round 1: the project's actual access pattern is
    ``docker compose exec -T postgres psql -U cloglog ...`` (see the
    Makefile's `dev` target). The original `docker exec` regex missed
    this two-word form. POSTGRES_DB in docker-compose.yml is ``cloglog``,
    so a connection without an explicit ``-d`` lands on the cloglog DB
    — the exact shape this hook is supposed to enforce against."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "docker compose exec -T postgres psql -U cloglog -c 'select 1'",
        },
    }
    result = _run_hook(payload)
    assert result.returncode != 0, (
        "block-direct-db.sh must reject `docker compose exec ... psql "
        "-U cloglog`. POSTGRES_DB defaults to `cloglog`, so this shape "
        "opens a raw session against the cloglog DB even without "
        "-d cloglog_dev / cloglog_prod."
    )


def test_hook_blocks_bare_psql_with_cloglog_user() -> None:
    """T-417 codex round 1: ``psql -U cloglog`` with no explicit -d
    connects to the default DB, which is ``cloglog`` per
    docker-compose.yml. The connection bypasses MCP and the audit log
    just like the dev/prod-named forms."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "psql -h 127.0.0.1 -U cloglog -c 'select 1'",
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


def test_hook_blocks_make_db_refresh_from_prod() -> None:
    """T-417 codex round 2: `make db-refresh-from-prod` is a Makefile
    wrapper that internally pg_dumps cloglog into cloglog_dev. The
    direct-psql regex only sees the outer `make ...` command and would
    let the wrapper through, opening a built-in bypass. Block the
    wrapper target by name."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "make db-refresh-from-prod"},
    }
    result = _run_hook(payload)
    assert result.returncode != 0, (
        "block-direct-db.sh must reject `make db-refresh-from-prod`. "
        "The recipe internally runs psql against cloglog and "
        "cloglog_dev — a shipped bypass of the direct-psql guard."
    )


def test_hook_allows_admin_psql_against_postgres_db() -> None:
    """T-417 codex round 2: documented admin commands like
    `psql -U cloglog -d postgres -c "CREATE DATABASE cloglog_dev ..."`
    target the `postgres` maintenance DB, not the cloglog board DB.
    The -U cloglog rule must NOT false-positive on these — they're
    bootstrap/admin operations, not board-DB access."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": (
                "psql -h 127.0.0.1 -U cloglog -d postgres "
                "-tAc \"SELECT 1 FROM pg_database WHERE datname='cloglog_dev'\""
            ),
        },
    }
    result = _run_hook(payload)
    assert result.returncode == 0, (
        "psql -U cloglog targeting -d postgres (admin DB) must be "
        "allowed. The Makefile's dev-env and db-refresh-from-prod "
        "recipes rely on this shape."
    )


def test_hook_allows_docker_compose_exec_psql_against_postgres_db() -> None:
    """T-417 codex round 2: same allowlist applies under `docker compose
    exec` — the `-d postgres` target is administrative, not board DB."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": (
                "docker compose exec -T postgres psql -U cloglog -d postgres "
                '-c "CREATE DATABASE cloglog_dev OWNER cloglog;"'
            ),
        },
    }
    result = _run_hook(payload)
    assert result.returncode == 0


def test_hook_blocks_compound_admin_then_board() -> None:
    """T-417 codex round 3: a compound command that leads with an
    allowed admin probe and then opens a forbidden board-DB session
    must still be rejected. Previously the `-d postgres` allowlist
    was evaluated against the whole flattened command, so prepending
    a maintenance call slipped a `psql -d cloglog_dev` past the gate.
    The hook now evaluates statements independently."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": (
                "psql -U cloglog -d postgres -c 'select 1'; "
                "psql -U cloglog -d cloglog_dev -c 'select 1'"
            ),
        },
    }
    result = _run_hook(payload)
    assert result.returncode != 0, (
        "Statement-scoped admin allowlist: an allowed `-d postgres` "
        "statement must not whitewash a sibling cloglog_dev statement "
        "on the same line. Round-3 regression."
    )


def test_hook_blocks_pg_dump_against_cloglog_dev() -> None:
    """T-417 codex round 3: `pg_dump` is a raw read path against the
    board DB. The earlier hook only matched `psql`, leaving
    `pg_dump -d cloglog_dev` as an unguarded bypass."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "pg_dump -h 127.0.0.1 -U cloglog -d cloglog_dev --schema-only > /tmp/x.sql",
        },
    }
    result = _run_hook(payload)
    assert result.returncode != 0


def test_hook_blocks_pg_dump_against_cloglog_default() -> None:
    """pg_dump against the default `cloglog` DB (POSTGRES_DB default
    per docker-compose.yml) is the same raw-read shape as the dev/prod
    forms — the Makefile's db-refresh-from-prod recipe uses exactly
    this command."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "pg_dump -h 127.0.0.1 -U cloglog -d cloglog --no-owner",
        },
    }
    result = _run_hook(payload)
    assert result.returncode != 0


def test_hook_blocks_docker_compose_exec_pg_dump() -> None:
    """T-417 codex round 3: same pg_dump bypass under
    `docker compose exec`."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "docker compose exec -T postgres pg_dump -U cloglog -d cloglog_dev",
        },
    }
    result = _run_hook(payload)
    assert result.returncode != 0


def test_hook_blocks_psql_d_cloglog_default() -> None:
    """T-417 codex round 4: `psql -U postgres -d cloglog` opens a raw
    session against the default cloglog board DB while authenticating
    as `postgres` (sidestepping the -U cloglog rule). Round 3 only
    matched cloglog_(dev|prod) on the DB target — bare `cloglog` was
    unguarded."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "psql -U postgres -d cloglog -c 'select 1'"},
    }
    result = _run_hook(payload)
    assert result.returncode != 0


def test_hook_blocks_psql_postgresql_uri_cloglog() -> None:
    """T-417 codex round 4: a postgresql:// URI ending in /cloglog is
    equivalent to `-d cloglog`. Must block."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "psql postgresql://postgres@127.0.0.1/cloglog -c 'select 1'",
        },
    }
    result = _run_hook(payload)
    assert result.returncode != 0


def test_hook_blocks_psql_long_username_cloglog() -> None:
    """T-417 codex round 4: the long --username spelling is equivalent
    to -U for connection purposes but slipped past the regex."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "psql --username cloglog -c 'select 1'"},
    }
    result = _run_hook(payload)
    assert result.returncode != 0


def test_hook_blocks_psql_long_username_equals_cloglog() -> None:
    """T-417 codex round 4: --username=cloglog form too."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "psql --username=cloglog -c 'select 1'"},
    }
    result = _run_hook(payload)
    assert result.returncode != 0


def test_hook_blocks_compound_admin_then_long_username() -> None:
    """T-417 codex round 4: the round-3 statement-scoped allowlist must
    cover the long --username spelling too. Lead with an allowed admin
    call, then sneak `psql --username cloglog ...` — must still block."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": (
                "psql --username cloglog -d postgres -c 'select 1' && "
                "psql --username cloglog -c 'select 1'"
            ),
        },
    }
    result = _run_hook(payload)
    assert result.returncode != 0


def test_hook_blocks_pgdatabase_env_cloglog_dev() -> None:
    """T-417 codex round 4: libpq env prefix `PGDATABASE=cloglog_dev`
    targets the protected DB without any CLI flag. The original
    regex only inspected args after the psql token, so this slipped
    through."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "PGDATABASE=cloglog_dev psql -U postgres -c 'select 1'",
        },
    }
    result = _run_hook(payload)
    assert result.returncode != 0


def test_hook_blocks_pgdatabase_env_cloglog_default() -> None:
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "PGDATABASE=cloglog psql -U postgres -c 'select 1'",
        },
    }
    result = _run_hook(payload)
    assert result.returncode != 0


def test_hook_blocks_pguser_env_cloglog() -> None:
    """T-417 codex round 4: PGUSER=cloglog as env prefix is equivalent
    to -U cloglog for the default-DB shape."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "PGUSER=cloglog psql -c 'select 1'"},
    }
    result = _run_hook(payload)
    assert result.returncode != 0


def test_hook_blocks_pgdatabase_env_pg_dump() -> None:
    """T-417 codex round 4: env prefix bypass via pg_dump too."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "PGDATABASE=cloglog_dev pg_dump -U postgres --schema-only",
        },
    }
    result = _run_hook(payload)
    assert result.returncode != 0


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
