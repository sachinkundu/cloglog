"""Pin tests: T-348.

The launch skill renders ``.cloglog/launch.sh`` from a heredoc; that script
is the only thing standing between a fresh ``bash`` after ``/clear`` and
``gh-app-token.py`` (which requires ``GH_APP_ID`` and
``GH_APP_INSTALLATION_ID`` in the process environment). Before T-348 the
launcher inherited those from the operator's shell — fragile, and broken
once T-329 introduced ``/clear`` between tasks. The fix is to read both
values from ``.cloglog/config.yaml`` and ``export`` them inside
``launch.sh`` itself, mirroring the ``_backend_url`` shape.

Pin shape:
  1. ``_gh_app_id`` / ``_gh_app_installation_id`` blocks exist in the
     heredoc, parse the keys via grep+sed (no ``import yaml``).
  2. The body exports both vars before invoking ``claude``.
  3. Operator-host literals (``3235173`` / ``120404294``) MUST NOT appear
     in any plugin file — they are host-specific and live in
     ``.cloglog/config.yaml`` only.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LAUNCH_SKILL = REPO_ROOT / "plugins/cloglog/skills/launch/SKILL.md"
PLUGIN_ROOT = REPO_ROOT / "plugins/cloglog"

OPERATOR_APP_ID = "3235173"
OPERATOR_INSTALLATION_ID = "120404294"


def _read(p: Path) -> str:
    assert p.exists(), f"{p} missing"
    return p.read_text(encoding="utf-8")


def test_launch_skill_defines_scalar_yaml_helper() -> None:
    """The heredoc must define a generic ``_read_scalar_yaml`` helper that
    parses YAML scalars via grep+sed (no python YAML lib).

    This is the workhorse used by both ``_gh_app_id`` and
    ``_gh_app_installation_id`` — pinning it once covers both readers.
    """
    body = _read(LAUNCH_SKILL)
    fn_match = re.search(r"_read_scalar_yaml\(\)\s*\{(.*?)\n\}", body, flags=re.DOTALL)
    assert fn_match, (
        "_read_scalar_yaml() helper missing from launch SKILL.md heredoc — "
        "the launcher must define a generic YAML scalar reader for "
        ".cloglog/local.yaml and .cloglog/config.yaml (T-348)."
    )
    fn_body = fn_match.group(1)
    assert "import yaml" not in fn_body, (
        "_read_scalar_yaml() must not embed the python YAML lib — see "
        "docs/invariants.md:76 and parse-yaml-scalar.sh."
    )
    assert "grep " in fn_body and "sed " in fn_body, (
        "_read_scalar_yaml() must read via grep+sed (the canonical scalar "
        "shape mirrored from parse-yaml-scalar.sh)."
    )


def test_launch_skill_readers_check_local_yaml_first() -> None:
    """``_gh_app_id`` and ``_gh_app_installation_id`` must check
    ``.cloglog/local.yaml`` (gitignored) before ``.cloglog/config.yaml``.

    Codex round 3 (MEDIUM) flagged that committing operator IDs to
    tracked config would push other clones at the wrong App installation.
    The fix splits resolution between gitignored ``local.yaml`` (preferred)
    and tracked ``config.yaml`` (fallback only); this pin enforces both
    readers walk that order.
    """
    body = _read(LAUNCH_SKILL)
    for fn_name, key in (
        ("_gh_app_id", "gh_app_id"),
        ("_gh_app_installation_id", "gh_app_installation_id"),
    ):
        fn_match = re.search(rf"{fn_name}\(\)\s*\{{(.*?)\n\}}", body, flags=re.DOTALL)
        assert fn_match, f"{fn_name}() block missing from launch SKILL.md (T-348)."
        fn_body = fn_match.group(1)
        local_idx = fn_body.find("local.yaml")
        config_idx = fn_body.find("config.yaml")
        assert local_idx >= 0 and config_idx >= 0, (
            f"{fn_name}() must reference both local.yaml (preferred, "
            "gitignored) and config.yaml (fallback). See T-348 round 3."
        )
        assert local_idx < config_idx, (
            f"{fn_name}() must check .cloglog/local.yaml BEFORE "
            ".cloglog/config.yaml — committed config is a fallback only "
            "(T-348 round 3)."
        )
        # Use the literal key name for the YAML lookup.
        assert key in fn_body, f"{fn_name}() must look up the {key!r} YAML key."


def test_launch_sh_exports_both_gh_app_env_vars() -> None:
    """The heredoc body must export both vars *before* ``claude`` runs.

    A reader that lands here as a future maintainer should see at a glance
    that the export lines are gated on a non-empty value — an empty config
    must not clobber an env var the operator has set in their shell RC
    (back-compat path).
    """
    body = _read(LAUNCH_SKILL)
    # Find the rendered launch.sh body (between the heredoc markers).
    heredoc = re.search(
        r"cat > \"\$\{WORKTREE_PATH\}/\.cloglog/launch\.sh\".*?<<\s*EOF\n(.*?)\nEOF\n",
        body,
        flags=re.DOTALL,
    )
    assert heredoc, "Could not locate launch.sh heredoc in launch SKILL.md"
    rendered = heredoc.group(1)

    # The export must come before the `claude --dangerously-skip-permissions` invocation.
    claude_idx = rendered.find("claude --dangerously-skip-permissions")
    assert claude_idx > 0, "claude invocation missing from launch.sh heredoc"
    pre_claude = rendered[:claude_idx]

    assert 'export GH_APP_ID="\\$_GH_APP_ID"' in pre_claude, (
        "launch.sh must export GH_APP_ID from the config-derived value "
        "before invoking claude. Without this, the github-bot skill's "
        "gh-app-token.py exits with 'env var required' on every task "
        "after a /clear."
    )
    assert 'export GH_APP_INSTALLATION_ID="\\$_GH_APP_INSTALLATION_ID"' in pre_claude, (
        "launch.sh must export GH_APP_INSTALLATION_ID before invoking claude."
    )

    # Gate on non-empty so a missing config key doesn't clobber a shell-RC export.
    assert '[[ -n "\\$_GH_APP_ID" ]] && export GH_APP_ID' in pre_claude, (
        "GH_APP_ID export must be gated on a non-empty config value — "
        "otherwise an operator who keeps the values in their shell RC "
        "(back-compat) would have them clobbered to empty."
    )
    assert '[[ -n "\\$_GH_APP_INSTALLATION_ID" ]] && export GH_APP_INSTALLATION_ID' in pre_claude


def test_no_operator_host_literals_in_plugin_or_tracked_cloglog_dir() -> None:
    """Operator-host App ID + Installation ID must NOT live in plugin files
    or in tracked ``.cloglog/`` files (codex round 3, MEDIUM).

    Two leak vectors this PR closes:

    * **Plugin files** would ship one operator's identity to every
      downstream repo that installs the plugin.
    * **Tracked ``.cloglog/config.yaml``** would push other clones of this
      repo at the wrong App installation.

    The values live in gitignored ``.cloglog/local.yaml`` (per host); this
    pin enforces both leak vectors stay closed. Other historical mentions
    elsewhere (work logs, contract spec fixtures) are out of scope for
    this PR — separate cleanup.
    """
    offenders: list[tuple[Path, int, str, str]] = []
    # Plugin-wide scan.
    for path in PLUGIN_ROOT.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for literal in (OPERATOR_APP_ID, OPERATOR_INSTALLATION_ID):
            if literal in text:
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if literal in line:
                        offenders.append((path, lineno, literal, line.strip()))
                        break
    # .cloglog/ tracked files — config.yaml in particular. Skip
    # local.yaml (that's the gitignored target home for these values).
    cloglog_dir = REPO_ROOT / ".cloglog"
    if cloglog_dir.is_dir():
        for path in cloglog_dir.iterdir():
            if not path.is_file() or path.name == "local.yaml":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for literal in (OPERATOR_APP_ID, OPERATOR_INSTALLATION_ID):
                if literal in text:
                    for lineno, line in enumerate(text.splitlines(), start=1):
                        if literal in line:
                            offenders.append((path, lineno, literal, line.strip()))
                            break
    assert not offenders, (
        "Operator-host-specific GitHub App IDs found in plugin files or "
        "in a tracked .cloglog/ file. These belong in the gitignored "
        ".cloglog/local.yaml only — any other location either leaks to "
        "plugin consumers or to other clones of this repo, both of which "
        "would mint tokens against the wrong App installation.\n"
        + "\n".join(
            f"  {p.relative_to(REPO_ROOT)}:{ln}: {literal!r} in {snippet!r}"
            for p, ln, literal, snippet in offenders
        )
    )


def test_config_yaml_does_not_carry_gh_app_keys() -> None:
    """``.cloglog/config.yaml`` is tracked — operator-host values must NOT
    live there (codex round 3, MEDIUM).

    The values belong in gitignored ``.cloglog/local.yaml``. A direct
    inversion of the original T-348 pin: the previous version asserted the
    keys were *present* in ``config.yaml``; codex correctly pointed out that
    pin baked the leak in.
    """
    cfg = REPO_ROOT / ".cloglog/config.yaml"
    text = _read(cfg)
    for key in ("gh_app_id", "gh_app_installation_id"):
        assert not re.search(rf"^{key}:", text, flags=re.MULTILINE), (
            f"{key} must NOT appear in tracked .cloglog/config.yaml — "
            "move it to the gitignored .cloglog/local.yaml. See T-348."
        )


def test_local_yaml_is_gitignored() -> None:
    """``.cloglog/local.yaml`` must be gitignored.

    Without this, an operator who follows the T-348 docs and writes their
    identifiers into ``.cloglog/local.yaml`` would accidentally commit them
    on the next ``git add .``.
    """
    gitignore = REPO_ROOT / ".gitignore"
    text = _read(gitignore)
    assert ".cloglog/local.yaml" in text.splitlines(), (
        ".gitignore must list .cloglog/local.yaml — operator-specific App IDs "
        "live there and must never be tracked. See T-348."
    )


def test_gh_app_token_script_resolves_from_local_yaml() -> None:
    """`gh-app-token.py` must resolve `GH_APP_ID` / `GH_APP_INSTALLATION_ID`
    from ``.cloglog/local.yaml`` itself, so callers (close-wave, reconcile,
    init, github-bot) work without per-skill env-priming plumbing.

    Codex round 3 (MEDIUM) flagged that several main-agent skills invoked
    the script directly assuming env-only — the centralised resolver in the
    script makes that assumption safe again.
    """
    script = REPO_ROOT / "plugins/cloglog/scripts/gh-app-token.py"
    text = _read(script)
    assert "local.yaml" in text, (
        "gh-app-token.py must look up .cloglog/local.yaml on every call — "
        "callers cannot rely on env priming alone (T-348 round 3)."
    )
    # Resolution order anchor — env first, then local.yaml, then config.yaml.
    # The function _resolve in the script encodes this; pin its presence.
    assert "_resolve" in text, (
        "gh-app-token.py must define a _resolve helper that walks "
        "env → local.yaml → config.yaml. See T-348."
    )
