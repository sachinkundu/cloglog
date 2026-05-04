"""T-382 pin: launch SKILL `_api_key` resolves per-project credentials.

The bug this guards against: on a host that runs cloglog and other
cloglog-managed projects (one shared backend, but each project has its own
project-scoped API key minted via `POST /api/v1/projects`), the global
`~/.cloglog/credentials` file held only one key. The wrong key got sent on
agent calls under the other projects' worktrees, producing silent 401/403
on `/api/v1/agents/unregister-by-path` and similar — the backend's
project-scoped auth rejects a key that doesn't match the project the
worktree belongs to.

The fix is per-project credential resolution: env → per-project file at
`~/.cloglog/credentials.d/<project_slug>` → legacy global file. The slug
comes from `<project_root>/.cloglog/config.yaml: project` with a
`basename($PROJECT_ROOT)` fallback.

This test renders the launch.sh that the SKILL emits, sources the helper
functions out of it, then asserts:

  * Two distinct projects with matching `credentials.d/<slug>` files each
    resolve to **their own** key — never the other project's.
  * A host with only the legacy global file (single-project setup) keeps
    working unchanged.
  * `CLOGLOG_API_KEY` env beats both file sources.
  * A path-traversal `project:` field in config.yaml is refused; resolution
    falls through to the basename slug rather than escaping the
    `credentials.d/` directory.

Mirrors `mcp-server/tests/credentials.test.ts` per-project assertions so
the bash and TS resolvers stay aligned (T-214 contract).
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

from tests.plugins.test_launch_skill_renders_clean_launch_sh import (
    _extract_emit_block,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = REPO_ROOT / "plugins/cloglog/skills/launch/SKILL.md"


def _render_launch_sh(tmp_path: Path) -> Path:
    """Render the launch.sh that the SKILL emits, then truncate it at the
    `cd "$WORKTREE_PATH"` line so the helper functions can be sourced
    without triggering the trap setup or the `claude` exec."""
    skill_text = SKILL_PATH.read_text()
    emit_block = _extract_emit_block(skill_text)

    wt_path = tmp_path / "wt"
    proj_root = tmp_path / "proj"
    (wt_path / ".cloglog").mkdir(parents=True)
    proj_root.mkdir(parents=True)

    result = subprocess.run(
        ["bash", "-c", emit_block],
        env={
            "PATH": "/usr/bin:/bin",
            "WORKTREE_PATH": str(wt_path),
            "PROJECT_ROOT": str(proj_root),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"emit block failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    rendered = (wt_path / ".cloglog" / "launch.sh").read_text()

    # Slice off everything from `cd "$WORKTREE_PATH"` onward — those lines
    # set traps and exec `claude`, which we do not want when sourcing.
    marker = 'cd "$WORKTREE_PATH"'
    assert marker in rendered, 'rendered launch.sh missing `cd "$WORKTREE_PATH"` exec line'
    helpers = rendered.split(marker, 1)[0]

    helpers_path = tmp_path / "helpers.sh"
    helpers_path.write_text(helpers)
    return helpers_path


def _resolve_key(
    helpers_path: Path,
    project_root: Path,
    fake_home: Path,
    *,
    env_key: str | None = None,
) -> str:
    """Source the helper bundle with $PROJECT_ROOT pointing at the given
    project, then echo the result of `_api_key`. Returns the resolved key
    (or empty string on miss)."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(fake_home),
        "PROJECT_ROOT": str(project_root),
    }
    if env_key is not None:
        env["CLOGLOG_API_KEY"] = env_key
    script = textwrap.dedent(f"""
        set -e
        # The rendered launch.sh hard-codes PROJECT_ROOT via sed substitution.
        # Source first, then override PROJECT_ROOT per-test (the helpers read
        # $PROJECT_ROOT at call time, not at definition time).
        source {helpers_path!s}
        PROJECT_ROOT="{project_root!s}"
        printf '%s' "$(_api_key)"
    """)
    result = subprocess.run(
        ["bash", "-c", script],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"helper resolve failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    return result.stdout


def _make_project(root: Path, project_field: str | None) -> Path:
    (root / ".cloglog").mkdir(parents=True, exist_ok=True)
    if project_field is not None:
        (root / ".cloglog" / "config.yaml").write_text(
            f"project: {project_field}\nbackend_url: http://127.0.0.1:8001\n"
        )
    return root


def _write_credfile(path: Path, key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"CLOGLOG_API_KEY={key}\n")
    os.chmod(path, 0o600)


def test_per_project_credentials_route_correctly(tmp_path: Path) -> None:
    """Two projects with their own credentials.d/<slug> each get their own key."""
    helpers = _render_launch_sh(tmp_path)
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    alpha = _make_project(tmp_path / "alpha-checkout", "alpha")
    beta = _make_project(tmp_path / "beta-checkout", "beta")

    _write_credfile(fake_home / ".cloglog" / "credentials.d" / "alpha", "alpha-key")
    _write_credfile(fake_home / ".cloglog" / "credentials.d" / "beta", "beta-key")
    # Legacy file with a third value to prove neither project falls through.
    _write_credfile(fake_home / ".cloglog" / "credentials", "legacy-fallback")

    assert _resolve_key(helpers, alpha, fake_home) == "alpha-key"
    assert _resolve_key(helpers, beta, fake_home) == "beta-key"


def test_legacy_only_host_still_works(tmp_path: Path) -> None:
    """Single-project hosts with only ~/.cloglog/credentials keep working."""
    helpers = _render_launch_sh(tmp_path)
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    project = _make_project(tmp_path / "only-project", "only")
    _write_credfile(fake_home / ".cloglog" / "credentials", "legacy-only")

    assert _resolve_key(helpers, project, fake_home) == "legacy-only"


def test_env_override_beats_file_sources(tmp_path: Path) -> None:
    helpers = _render_launch_sh(tmp_path)
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    project = _make_project(tmp_path / "env-wins", "envwins")
    _write_credfile(fake_home / ".cloglog" / "credentials.d" / "envwins", "project-key")
    _write_credfile(fake_home / ".cloglog" / "credentials", "legacy-key")

    assert _resolve_key(helpers, project, fake_home, env_key="env-key") == "env-key"


def test_path_traversal_slug_is_refused(tmp_path: Path) -> None:
    """A `project: ../escape` field must not let the resolver read outside
    `~/.cloglog/credentials.d/`. The bash slug validator must reject it and
    fall back to basename($PROJECT_ROOT) — `safe-basename` here."""
    helpers = _render_launch_sh(tmp_path)
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    project = _make_project(tmp_path / "safe-basename", "../escape")
    # Place a "safe-basename" file (the basename fallback) AND an "escape"
    # file outside credentials.d/ to prove neither traversal nor field-trust
    # wins. If the validator failed, the escape file's content would leak in.
    _write_credfile(fake_home / ".cloglog" / "credentials.d" / "safe-basename", "basename-key")
    _write_credfile(fake_home / ".cloglog" / "escape", "ESCAPED-IF-LEAKED")

    assert _resolve_key(helpers, project, fake_home) == "basename-key"


def test_present_but_blank_per_project_file_blocks_legacy_fallback(tmp_path: Path) -> None:
    """T-382 codex round 3: once ~/.cloglog/credentials.d/<slug> EXISTS,
    the resolver MUST refuse to fall back to the legacy global file even
    if the per-project file is unusable. The legacy file may hold a
    different project's key, and silently sending it on signal-triggered
    shutdown recreates the wrong-project bug T-382 was filed to remove.

    This test seeds:
      - ~/.cloglog/credentials.d/<slug>  (BLANK — no CLOGLOG_API_KEY)
      - ~/.cloglog/credentials           (legacy with another project's key)

    and asserts _api_key returns empty (so _unregister_fallback skips the
    POST), NOT the legacy key.
    """
    helpers = _render_launch_sh(tmp_path)
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    project = _make_project(tmp_path / "blank-perproject", "blankperproject")
    cred_d = fake_home / ".cloglog" / "credentials.d"
    cred_d.mkdir(parents=True)
    blank_file = cred_d / "blankperproject"
    blank_file.write_text("# blank\nOTHER=value\n")
    os.chmod(blank_file, 0o600)
    _write_credfile(fake_home / ".cloglog" / "credentials", "LEGACY-WRONG-PROJECT")

    resolved = _resolve_key(helpers, project, fake_home)
    assert resolved == "", (
        f"Expected empty (refuse fallback), got {resolved!r}. The legacy file "
        "must NOT shadow a present-but-broken per-project file."
    )


def test_present_but_unreadable_per_project_file_blocks_legacy_fallback(tmp_path: Path) -> None:
    """Same invariant as above for the chmod-000 case."""
    helpers = _render_launch_sh(tmp_path)
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    project = _make_project(tmp_path / "unreadable-perproject", "unreadable")
    cred_d = fake_home / ".cloglog" / "credentials.d"
    cred_d.mkdir(parents=True)
    bad_file = cred_d / "unreadable"
    bad_file.write_text("CLOGLOG_API_KEY=this-is-actually-the-right-key\n")
    os.chmod(bad_file, 0o000)
    _write_credfile(fake_home / ".cloglog" / "credentials", "LEGACY-WRONG-PROJECT")

    try:
        resolved = _resolve_key(helpers, project, fake_home)
        assert resolved == "", (
            f"Expected empty (refuse fallback), got {resolved!r}. Unreadable "
            "per-project file must veto the legacy fallback."
        )
    finally:
        os.chmod(bad_file, 0o600)  # so cleanup can rm


def test_project_id_set_missing_per_project_file_blocks_legacy_fallback(tmp_path: Path) -> None:
    """T-398 Guard 3: when project_id is in config.yaml but no per-project
    credentials file exists, _api_key() must return empty — NOT the legacy
    global file's key.

    The T-398 strict-fallback guard in the MCP server (loadApiKey) and the
    shared hook helper (resolve-api-key.sh) both refuse the legacy file when
    project_id is set. launch.sh's _api_key must be consistent or the signal-
    trap _unregister_fallback POST authenticates as the wrong project on the
    shutdown path.

    Seeds:
      - .cloglog/config.yaml with both `project:` AND `project_id:`
      - NO credentials.d/<slug> file
      - ~/.cloglog/credentials with another project's key

    Asserts _api_key returns empty.
    """
    helpers = _render_launch_sh(tmp_path)
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    project_root = tmp_path / "myproject"
    project_root.mkdir()
    (project_root / ".cloglog").mkdir()
    (project_root / ".cloglog" / "config.yaml").write_text(
        "project: myproject\nproject_id: some-uuid-here\nbackend_url: http://127.0.0.1:8001\n"
    )

    # No credentials.d/myproject file — per-project file is absent.
    # Legacy global file exists with ANOTHER project's key.
    _write_credfile(fake_home / ".cloglog" / "credentials", "WRONG-PROJECT-KEY")

    resolved = _resolve_key(helpers, project_root, fake_home)
    assert resolved == "", (
        f"Expected empty (T-398 Guard 3 — refuse legacy fallback when project_id set), "
        f"got {resolved!r}. When project_id is in config.yaml, _api_key must not fall "
        "through to ~/.cloglog/credentials — the key there may belong to another project."
    )


def test_skill_documents_per_project_resolution_order() -> None:
    """Text-level pin: SKILL.md `_api_key` block names the new resolution
    chain. Stops a future edit from silently reverting to the old global-only
    behaviour."""
    skill_text = SKILL_PATH.read_text()
    assert "_project_slug" in skill_text, (
        "SKILL.md `_api_key` must call `_project_slug` for per-project resolution (T-382)."
    )
    assert "credentials.d/" in skill_text, (
        "SKILL.md `_api_key` must reference `~/.cloglog/credentials.d/<slug>` (T-382)."
    )
