"""Pin tests: T-398 Guard 2.

register_agent must verify that the backend-returned project_id matches the
project_id recorded in .cloglog/config.yaml for the worktree. A mismatch
means the MCP server authenticated with a key belonging to a different
project — the antisocial/cloglog incident.

These pins enforce the structural presence of the check in server.ts:
1. server.ts imports resolveProjectId from credentials.ts.
2. The register_agent handler reads configProjectId from the worktree's
   config.yaml.
3. The mismatch error message names expected/actual/credential-path/remediation.
4. credentials.ts exports resolveProjectId.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_TS = REPO_ROOT / "mcp-server/src/server.ts"
CREDENTIALS_TS = REPO_ROOT / "mcp-server/src/credentials.ts"


def _read_server() -> str:
    assert SERVER_TS.exists(), f"{SERVER_TS} missing — fix path or file was moved"
    return SERVER_TS.read_text(encoding="utf-8")


def _read_credentials() -> str:
    assert CREDENTIALS_TS.exists(), f"{CREDENTIALS_TS} missing — fix path"
    return CREDENTIALS_TS.read_text(encoding="utf-8")


def test_server_imports_resolve_project_id() -> None:
    """server.ts must import resolveProjectId from credentials.ts."""
    src = _read_server()
    assert "resolveProjectId" in src, (
        "server.ts must import and use resolveProjectId from credentials.ts "
        "(T-398 Guard 2: register_agent verifies project_id)."
    )


def test_server_imports_find_project_root() -> None:
    """server.ts must import findProjectRoot to locate config.yaml from worktree_path."""
    src = _read_server()
    assert "findProjectRoot" in src, (
        "server.ts must import findProjectRoot from credentials.ts to walk up "
        "from worktree_path to the .cloglog/config.yaml that carries project_id."
    )


def test_register_agent_checks_config_project_id() -> None:
    """register_agent must read configProjectId from the worktree's config.yaml."""
    src = _read_server()
    assert "configProjectId" in src, (
        "register_agent must read configProjectId from .cloglog/config.yaml "
        "(T-398 Guard 2). The handler compares it against the backend-returned "
        "project_id and refuses on mismatch."
    )


def test_register_agent_mismatch_names_expected_and_actual() -> None:
    """The mismatch error must name both expected (config) and actual (backend) IDs."""
    src = _read_server()
    assert "expected" in src and "actual" in src, (
        "register_agent mismatch error must label the config.yaml value as "
        "'expected' and the backend value as 'actual' so the operator can "
        "immediately see which one is wrong."
    )
    assert "project_id mismatch" in src, (
        "register_agent mismatch error must contain 'project_id mismatch' "
        "as the leading diagnosis line."
    )


def test_register_agent_mismatch_mentions_credentials_d() -> None:
    """The mismatch error must reference credentials.d in the remediation."""
    src = _read_server()
    assert "credentials.d" in src, (
        "register_agent mismatch diagnostic must mention credentials.d/<slug> "
        "so the operator knows where to look to fix the key."
    )


def test_credentials_ts_exports_resolve_project_id() -> None:
    """credentials.ts must export resolveProjectId for server.ts to use."""
    src = _read_credentials()
    assert "export function resolveProjectId" in src, (
        "credentials.ts must export resolveProjectId() — the function that "
        "reads project_id from .cloglog/config.yaml (T-398 Guard 2)."
    )


def test_credentials_ts_exports_project_id_set_missing_error() -> None:
    """credentials.ts must export ProjectIdSetMissingCredentialsError (Guard 3)."""
    src = _read_credentials()
    assert "export class ProjectIdSetMissingCredentialsError" in src, (
        "credentials.ts must export ProjectIdSetMissingCredentialsError — "
        "the error thrown when project_id is set but no per-project credentials "
        "file exists (T-398 Guard 3 strict fallback)."
    )
