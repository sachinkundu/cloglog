"""Pin tests: T-319 + T-321 + T-323.

T-319: init Steps 3 and 7a must resolve every `<...>` / `/path/to/...`
placeholder to a concrete absolute path before writing files.

T-321: init Step 4a must populate `.cloglog/config.yaml` with `project_id`
(seeded from the `mcp__cloglog__create_project` response in Step 2) and a
*commented-out* `worktree_scopes` template. A live mapping cannot be
auto-generated because protect-worktree-writes derives the scope key from
`basename(worktree) - "wt-"` and init has no way to predict the launcher's
naming convention; live keys would silently leave the guard in allow-all
mode (codex review on PR #260).

T-323: post-init artifacts (`.claude/settings.json`, `.cloglog/config.yaml`)
must not bake any cloglog operator-host literal into a fresh project. The
brand surface is intentionally retained — `cloglog`, `mcp__cloglog__*`,
the MCP server name `cloglog-mcp`, and `~/.cloglog/credentials` ship with
the plugin and identify it on the wire. Everything else (`cloglog.voxdez.com`,
`../cloglog-prod`, reviewer-bot logins, `/home/sachin/...`) is host- or
project-specific and must NOT appear in init output. `.cloglog/launch.sh`
is intentionally exempt from this check (the launcher must contain absolute
host paths per T-284 — pinned by `tests/plugins/test_launch_skill_uses_abs_paths.py`).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INIT_SKILL = REPO_ROOT / "plugins/cloglog/skills/init/SKILL.md"

PLACEHOLDERS = [
    "<absolute-path-to-project>",
    "<path to plugins/cloglog>",
    "/path/to/mcp-server/dist/index.js",
]


def _read_skill() -> str:
    assert INIT_SKILL.exists(), f"{INIT_SKILL} missing"
    return INIT_SKILL.read_text(encoding="utf-8")


def _section(body: str, start_marker: str, stop_prefix: str) -> str:
    """Slice [start_marker, next line starting with stop_prefix)."""
    lines = body.splitlines()
    out: list[str] = []
    capturing = False
    for line in lines:
        if line.startswith(start_marker):
            capturing = True
            out.append(line)
            continue
        if capturing:
            if line.startswith(stop_prefix) and not line.startswith(start_marker):
                break
            out.append(line)
    assert out, f"Could not locate {start_marker!r} section"
    return "\n".join(out)


def _first_bash_block(text: str) -> str:
    m = re.search(r"```bash\n(.*?)```", text, re.DOTALL)
    assert m, "No ```bash block found"
    return m.group(1)


# ---------------------------------------------------------------------------
# Static pins — placeholders must not appear inside the executable Step 3 block
# ---------------------------------------------------------------------------


def test_step3_bash_block_has_no_literal_placeholders() -> None:
    step3 = _section(_read_skill(), "## Step 3:", "## Step ")
    block = _first_bash_block(step3)
    for needle in PLACEHOLDERS:
        assert needle not in block, (
            f"Step 3 bash block still contains literal placeholder {needle!r}. "
            "Resolve it from ${CLAUDE_PLUGIN_ROOT} / git rev-parse before writing settings.json."
        )


def test_step3_resolves_via_plugin_root_and_python_merge() -> None:
    step3 = _section(_read_skill(), "## Step 3:", "## Step ")
    block = _first_bash_block(step3)
    assert "${CLAUDE_PLUGIN_ROOT" in block, (
        "Step 3 must resolve PLUGIN_ROOT from ${CLAUDE_PLUGIN_ROOT} so the "
        "bootstrap hook and mcp-server entry land as absolute paths."
    )
    assert "session-bootstrap.sh" in block, (
        "Step 3 must reference hooks/session-bootstrap.sh — the SessionStart "
        "hook target is the cloglog session bootstrap."
    )
    assert "mcp-server/dist/index.js" in block, (
        "Step 3 must compute the mcp-server/dist/index.js entry path so "
        "the resolved absolute path lands in args[0]."
    )


def test_step7a_uses_claude_plugin_root() -> None:
    step7a = _section(_read_skill(), "### 7a.", "### ")
    block = _first_bash_block(step7a)
    assert "<path to plugins/cloglog>" not in block, (
        "Step 7a must not emit literal `<path to plugins/cloglog>` — "
        "operators copy code blocks verbatim."
    )
    assert "${CLAUDE_PLUGIN_ROOT" in block, (
        "Step 7a must resolve PLUGIN_ROOT from ${CLAUDE_PLUGIN_ROOT}."
    )


# ---------------------------------------------------------------------------
# Behavioural pin — execute the Step 3 block against a fresh tmp repo
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_plugin_root(tmp_path: Path) -> Path:
    """Layout: <root>/plugin/hooks/session-bootstrap.sh + sibling mcp-server build."""
    plugin = tmp_path / "plugin"
    (plugin / "hooks").mkdir(parents=True)
    bootstrap = plugin / "hooks" / "session-bootstrap.sh"
    bootstrap.write_text("#!/usr/bin/env bash\nexit 0\n")
    bootstrap.chmod(0o755)

    mcp_dist = tmp_path / "mcp-server" / "dist"
    mcp_dist.mkdir(parents=True)
    (mcp_dist / "index.js").write_text("// fake build\n")
    return plugin


def test_step3_block_writes_settings_with_no_placeholders(
    tmp_path: Path, fake_plugin_root: Path
) -> None:
    """Execute the Step 3 bash block in a fresh tmp repo and verify output."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=x@y",
            "-c",
            "user.name=x",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
    )

    block = _first_bash_block(_section(_read_skill(), "## Step 3:", "## Step "))

    env = {
        **os.environ,
        "CLAUDE_PLUGIN_ROOT": str(fake_plugin_root),
        "BACKEND_URL": "http://127.0.0.1:8001",
    }
    # Run with -e -u so any unresolved-placeholder mistake (e.g. unset var)
    # surfaces as a non-zero exit instead of a silent literal write.
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", block],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Step 3 block failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    settings_path = repo / ".claude" / "settings.json"
    mcp_path = repo / ".mcp.json"
    assert settings_path.exists(), "Step 3 did not write .claude/settings.json"
    assert mcp_path.exists(), (
        "Step 3 did not write .mcp.json — Claude Code loads MCP servers from "
        ".mcp.json at the project root, not .claude/settings.json (T-344)."
    )
    settings_raw = settings_path.read_text()
    mcp_raw = mcp_path.read_text()

    for needle in PLACEHOLDERS:
        assert needle not in settings_raw, (
            f".claude/settings.json contains literal placeholder {needle!r} "
            "after Step 3 — placeholders must be resolved before write."
        )
        assert needle not in mcp_raw, (
            f".mcp.json contains literal placeholder {needle!r} after Step 3 — "
            "placeholders must be resolved before write."
        )

    settings_data = json.loads(settings_raw)
    mcp_data = json.loads(mcp_raw)

    # T-344: hooks belong in settings.json, mcpServers in .mcp.json. The two
    # files MUST NOT cross-contaminate — a stale mcpServers key in
    # settings.json is the original bug this test guards against.
    assert "mcpServers" not in settings_data, (
        ".claude/settings.json must NOT contain `mcpServers` (T-344). "
        "Claude Code does not load MCP servers from this file; the entry "
        "must live in .mcp.json at the project root."
    )
    assert "hooks" not in mcp_data, (
        ".mcp.json must NOT contain `hooks` — that key belongs in "
        ".claude/settings.json. Crossed writes mean the merge has regressed."
    )

    hook_cmd = settings_data["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    args = mcp_data["mcpServers"]["cloglog"]["args"]
    backend = mcp_data["mcpServers"]["cloglog"]["env"]["CLOGLOG_URL"]

    assert hook_cmd == str(fake_plugin_root / "hooks" / "session-bootstrap.sh"), (
        f"SessionStart command should be the resolved bootstrap path, got {hook_cmd!r}"
    )
    assert Path(hook_cmd).is_absolute(), "Bootstrap hook command must be absolute"
    assert len(args) == 1 and Path(args[0]).is_absolute(), (
        f"mcp-server args[0] must be an absolute path, got {args!r}"
    )
    assert args[0].endswith("/mcp-server/dist/index.js"), (
        f"mcp-server args[0] should resolve to dist/index.js, got {args[0]!r}"
    )
    assert backend == "http://127.0.0.1:8001"

    # T-214 invariant re-affirmed at the new file location.
    cloglog_env = mcp_data["mcpServers"]["cloglog"].get("env", {})
    assert "CLOGLOG_API_KEY" not in cloglog_env, (
        "Step 3 must NEVER write CLOGLOG_API_KEY into .mcp.json — the MCP "
        "server reads it from env or ~/.cloglog/credentials only (T-214)."
    )
    assert "CLOGLOG_API_KEY" not in mcp_raw, (
        "CLOGLOG_API_KEY must not appear anywhere in .mcp.json (T-214)."
    )


# ---------------------------------------------------------------------------
# T-344 — Step 3 auto-repair migrates legacy mcpServers-in-settings.json
# ---------------------------------------------------------------------------


def test_step3_migrates_legacy_mcp_servers_block_to_mcp_json(
    tmp_path: Path, fake_plugin_root: Path
) -> None:
    """A project initialized with the broken pre-T-344 layout has
    `mcpServers.cloglog` inside `.claude/settings.json` and no `.mcp.json`.
    Re-running Step 3 must move the entry into `.mcp.json` and strip
    `mcpServers` from settings.json. The repair is idempotent — running
    Step 3 a second time on the now-correct layout must be a no-op.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=x@y",
            "-c",
            "user.name=x",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
    )

    # Seed the broken legacy layout: mcpServers in settings.json, no .mcp.json.
    legacy_settings_dir = repo / ".claude"
    legacy_settings_dir.mkdir()
    legacy_settings = legacy_settings_dir / "settings.json"
    legacy_settings.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cloglog": {
                        "command": "node",
                        "args": ["/legacy/path/to/index.js"],
                        "env": {"CLOGLOG_URL": "http://127.0.0.1:8001"},
                    }
                }
            },
            indent=2,
        )
        + "\n"
    )

    block = _first_bash_block(_section(_read_skill(), "## Step 3:", "## Step "))
    env = {
        **os.environ,
        "CLAUDE_PLUGIN_ROOT": str(fake_plugin_root),
        "BACKEND_URL": "http://127.0.0.1:8001",
    }

    # Run Step 3 once — migration kicks in.
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", block],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Step 3 migration run failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    settings = json.loads(legacy_settings.read_text())
    mcp = json.loads((repo / ".mcp.json").read_text())

    assert "mcpServers" not in settings, (
        "Step 3 migration must STRIP `mcpServers` from .claude/settings.json. "
        "Leaving it in place keeps the broken layout next to the correct one."
    )
    assert "cloglog" in mcp.get("mcpServers", {}), (
        "Step 3 migration must MOVE `mcpServers.cloglog` into .mcp.json."
    )
    # The migrated entry MUST reflect the freshly resolved MCP_INDEX, not the
    # stale `/legacy/path/to/index.js` from the seed. The merge runs after the
    # migration and overwrites the cloglog entry with current paths.
    args = mcp["mcpServers"]["cloglog"]["args"]
    assert args[0].endswith("/mcp-server/dist/index.js"), (
        f"Migration must refresh args to the resolved MCP_INDEX, got {args!r}"
    )
    assert "/legacy/path/to/index.js" not in (repo / ".mcp.json").read_text(), (
        "Migration left the stale legacy index path in place — expected the "
        "merge step to overwrite the cloglog entry with current resolved paths."
    )

    # Run Step 3 again — must be a clean no-op (no exception, no duplication).
    result2 = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", block],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result2.returncode == 0, (
        f"Step 3 re-run failed: stdout={result2.stdout!r} stderr={result2.stderr!r}"
    )
    settings2 = json.loads(legacy_settings.read_text())
    mcp2 = json.loads((repo / ".mcp.json").read_text())
    assert "mcpServers" not in settings2
    assert list(mcp2["mcpServers"].keys()) == ["cloglog"], (
        "Re-running Step 3 must leave .mcp.json's mcpServers stable, not duplicate."
    )


# ---------------------------------------------------------------------------
# T-321 — Step 4a writes project_id and worktree_scopes
# ---------------------------------------------------------------------------


def _step4a_bash_block(skill_body: str) -> str:
    """Return the bash block under '#### 4a.1'."""
    section = _section(skill_body, "#### 4a.1", "## ")
    return _first_bash_block(section)


def _yaml_template(skill_body: str) -> str:
    """Return the first ```yaml block in Step 4a (the config.yaml template)."""
    section = _section(skill_body, "### 4a.", "### ")
    m = re.search(r"```yaml\n(.*?)```", section, re.DOTALL)
    assert m, "No ```yaml block found in Step 4a"
    return m.group(1)


def test_step4a_yaml_template_documents_project_id_and_worktree_scopes() -> None:
    body = _read_skill()
    step4a = _section(body, "### 4a.", "### ")
    assert "project_id:" in step4a, (
        "Step 4a must document `project_id` in the config.yaml template — "
        "consumers that read project_id from config break without it."
    )
    assert "worktree_scopes:" in step4a, (
        "Step 4a must document `worktree_scopes` so the protect-worktree-writes "
        "hook has a scope map on a fresh project."
    )


def test_step4a1_bash_block_skips_when_worktree_scopes_already_present(
    tmp_path: Path,
) -> None:
    """Idempotency: re-running Step 4a.1 on a config that already has scopes is a no-op."""
    cfg = tmp_path / ".cloglog" / "config.yaml"
    cfg.parent.mkdir()
    cfg.write_text(
        "project_id: deadbeef-aaaa-bbbb-cccc-000000000001\n"
        "worktree_scopes:\n"
        "  custom: [packages/]\n"
    )
    block = _step4a_bash_block(_read_skill())
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", block],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    # File is unchanged — no duplicate worktree_scopes key, no auto-detect overwrite.
    body = cfg.read_text()
    assert body.count("worktree_scopes:") == 1
    assert "custom: [packages/]" in body


def test_step4a1_always_emits_commented_template(tmp_path: Path) -> None:
    """Step 4a.1 always appends a commented-out template, never a live mapping.

    The protect-worktree-writes hook strips `wt-` from a worktree's basename
    and looks the remainder up in `worktree_scopes` (with prefix matching).
    Since init can't predict the launcher's worktree-naming convention,
    auto-detected keys like `backend`/`frontend`/`mcp` would never match
    real worktree names like `wt-t321-init-config-gen`, leaving the hook
    in allow-all mode while pretending to enforce. Always-commented is the
    only honest default.
    """
    project_id = "11111111-2222-3333-4444-555555555555"
    cfg = tmp_path / ".cloglog" / "config.yaml"
    cfg.parent.mkdir()
    cfg.write_text(
        f"project_name: demo\nproject_id: {project_id}\nbackend_url: http://127.0.0.1:8001\n"
    )
    # Layout that previously triggered auto-detection. Must NOT change behaviour.
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "mcp-server").mkdir()

    block = _step4a_bash_block(_read_skill())
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", block],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    body = cfg.read_text()
    assert f"project_id: {project_id}" in body, (
        "Step 4a.1 must NOT touch project_id — only append the worktree_scopes template."
    )
    assert re.search(r"^worktree_scopes:", body, re.MULTILINE) is None, (
        "Step 4a.1 must NEVER emit a live worktree_scopes mapping — scope keys "
        "depend on the launcher's wt-<scope> convention, which init can't "
        "predict. A live mapping with non-matching keys silently disables the "
        "protect-worktree-writes guard."
    )
    assert "# worktree_scopes:" in body, (
        "Step 4a.1 must emit a commented-out worktree_scopes template so "
        "operators can uncomment and adapt to their launcher convention."
    )


def test_step4a_yaml_template_keeps_worktree_scopes_commented() -> None:
    """YAML template shown to operators must keep worktree_scopes commented, not live."""
    yaml = _yaml_template(_read_skill())
    # `worktree_scopes:` (uncommented) must not appear as a live key in the
    # template — only `# worktree_scopes:` is acceptable. Match line starts.
    live_lines = [line for line in yaml.splitlines() if re.match(r"^worktree_scopes:", line)]
    assert not live_lines, (
        "YAML template must show worktree_scopes commented out — operators "
        f"copy the template verbatim. Offending lines: {live_lines}"
    )
    assert any(line.startswith("# worktree_scopes:") for line in yaml.splitlines()), (
        "YAML template must include a commented `# worktree_scopes:` placeholder."
    )


def test_step4a1_fails_loudly_when_project_id_missing(tmp_path: Path) -> None:
    """Step 4a.1 must refuse to run when project_id is absent — Step 2 should have seeded it."""
    cfg = tmp_path / ".cloglog" / "config.yaml"
    cfg.parent.mkdir()
    cfg.write_text("project_name: missing-id\n")  # no project_id

    block = _step4a_bash_block(_read_skill())
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", block],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        "Step 4a.1 must fail when project_id is missing — silently appending "
        "worktree_scopes onto a half-bootstrapped config hides the Step 2 bug."
    )
    assert "project_id" in result.stderr or "project_id" in result.stdout


# ---------------------------------------------------------------------------
# T-323 — post-init outputs carry no cloglog-host literals (carve out brand)
# ---------------------------------------------------------------------------

# Strings the audit (docs/design/plugin-portability-audit.md §8) flags as
# host- or project-specific. None of these may appear in a fresh-repo init
# output. Listed verbatim so a regex-typo can't accidentally widen the pin.
HOST_LITERALS = (
    "cloglog.voxdez.com",  # webhook tunnel host
    "cloglog-webhooks",  # cloudflared tunnel name
    "cloglog-dashboard-dev",  # dashboard auth key
    "../cloglog-prod",  # cloglog dev/prod sibling-clone topology
    "cloglog-codex-reviewer[bot]",  # cloglog-deployment reviewer App
    "cloglog-opencode-reviewer[bot]",
    "/home/sachin",  # operator-host home path
)

# Brand surface: intentionally retained — `init` writes these on purpose so
# the plugin identifies itself on the wire. The pins below assert these
# survive the host-literal scan (i.e. the regex shape doesn't accidentally
# strip them too).
#
# T-344: `mcpServers.cloglog` now lives in `.mcp.json`, not `.claude/settings.json`.
# The brand surface in settings.json is just the `cloglog` literal that lands
# in the SessionStart hook path (resolved from ${CLAUDE_PLUGIN_ROOT}). The
# `mcp-server/dist/index.js` literal moved with the block to `.mcp.json` and
# is asserted by the new `.mcp.json`-side test below.
BRAND_SURFACE_SETTINGS = (
    "cloglog",  # plugin name reaches settings.json via the resolved bootstrap path
)
BRAND_SURFACE_MCP_JSON = (
    "cloglog",  # MCP server entry name in .mcp.json
    "mcp-server/dist/index.js",  # plugin-resolved entry point
)


def test_step3_settings_carries_no_host_specific_literals(
    tmp_path: Path, fake_plugin_root: Path
) -> None:
    """`.claude/settings.json` written by Step 3 must not embed any cloglog
    operator-host literal. The plugin is project-agnostic; init runs in a
    *new* project's tree, so a settings.json that names cloglog's tunnel,
    dashboard key, prod-sibling path, reviewer bots, or the operator's
    home directory has leaked dev-environment state into a downstream
    project.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=x@y",
            "-c",
            "user.name=x",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
    )

    block = _first_bash_block(_section(_read_skill(), "## Step 3:", "## Step "))
    env = {
        **os.environ,
        "CLAUDE_PLUGIN_ROOT": str(fake_plugin_root),
        "BACKEND_URL": "http://127.0.0.1:8001",
    }
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", block],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Step 3 block failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    settings = (repo / ".claude" / "settings.json").read_text()
    mcp_json = (repo / ".mcp.json").read_text()
    for needle in HOST_LITERALS:
        assert needle not in settings, (
            f".claude/settings.json contains host-specific literal {needle!r} "
            "after Step 3 — this is operator-environment state leaking into a "
            "fresh project. Move the value behind a config key or env var."
        )
        assert needle not in mcp_json, (
            f".mcp.json contains host-specific literal {needle!r} after Step 3 — "
            "this is operator-environment state leaking into a fresh project."
        )

    # Carve-out: brand surface must SURVIVE the no-literal sweep above. A
    # future widened regex that strips `cloglog` from these files would
    # rename the MCP server and break every `mcp__cloglog__*` reference.
    # Post T-344 the brand surface lives in .mcp.json (where mcpServers.cloglog
    # is now written); settings.json carries only the SessionStart hook and
    # need not include a cloglog literal in this fixture (real plugin paths
    # contain "cloglog" but the fake_plugin_root fixture is named "plugin").
    for needle in BRAND_SURFACE_MCP_JSON:
        assert needle in mcp_json, (
            f"Step 3 lost brand-surface literal {needle!r} from .mcp.json — "
            "a regex over-broad enough to strip this would rename the MCP server."
        )


def test_step4a_config_yaml_carries_no_host_specific_literals(tmp_path: Path) -> None:
    """The `.cloglog/config.yaml` Step 4a appends to must stay
    project-portable. Cloglog's own config legitimately carries
    `prod_worktree_path: ../cloglog-prod` and worktree-scope keys, but
    that's hand-edited *after* init — init's own template/append must not
    bake the cloglog dev/prod topology into a fresh project.
    """
    project_id = "11111111-2222-3333-4444-555555555555"
    cfg = tmp_path / ".cloglog" / "config.yaml"
    cfg.parent.mkdir()
    cfg.write_text(
        f"project_name: demo\nproject_id: {project_id}\nbackend_url: http://127.0.0.1:8001\n"
    )

    block = _step4a_bash_block(_read_skill())
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", block],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    body = cfg.read_text()
    for needle in HOST_LITERALS:
        assert needle not in body, (
            f".cloglog/config.yaml contains host-specific literal {needle!r} "
            "after Step 4a — operator-environment state must not leak into the "
            "fresh project's config template."
        )
