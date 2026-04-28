"""Pin tests: T-319 + T-321.

T-319: init Steps 3 and 7a must resolve every `<...>` / `/path/to/...`
placeholder to a concrete absolute path before writing files.

T-321: init Step 4a must populate `.cloglog/config.yaml` with `project_id`
(seeded from the `mcp__cloglog__create_project` response in Step 2) and a
*commented-out* `worktree_scopes` template. A live mapping cannot be
auto-generated because protect-worktree-writes derives the scope key from
`basename(worktree) - "wt-"` and init has no way to predict the launcher's
naming convention; live keys would silently leave the guard in allow-all
mode (codex review on PR #260).
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
    assert settings_path.exists(), "Step 3 did not write .claude/settings.json"
    raw = settings_path.read_text()

    for needle in PLACEHOLDERS:
        assert needle not in raw, (
            f".claude/settings.json contains literal placeholder {needle!r} "
            "after Step 3 — placeholders must be resolved before write."
        )

    data = json.loads(raw)
    hook_cmd = data["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    args = data["mcpServers"]["cloglog"]["args"]
    backend = data["mcpServers"]["cloglog"]["env"]["CLOGLOG_URL"]

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
