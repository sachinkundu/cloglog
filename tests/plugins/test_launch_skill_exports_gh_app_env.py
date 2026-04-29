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


def test_launch_skill_defines_gh_app_id_reader() -> None:
    body = _read(LAUNCH_SKILL)
    fn_match = re.search(r"_gh_app_id\(\)\s*\{(.*?)\n\}", body, flags=re.DOTALL)
    assert fn_match, (
        "_gh_app_id() block missing from launch SKILL.md heredoc — "
        "the launcher must read gh_app_id from .cloglog/config.yaml so "
        "worktree agents can mint a bot token after /clear (T-348)."
    )
    fn_body = fn_match.group(1)
    assert "import yaml" not in fn_body, (
        "_gh_app_id() must not embed `python3 -c 'import yaml'` — see "
        "docs/invariants.md:76 and parse-yaml-scalar.sh."
    )
    assert "grep '^gh_app_id:'" in fn_body, (
        "_gh_app_id() must read via the grep+sed shape that mirrors "
        "_backend_url and parse-yaml-scalar.sh."
    )


def test_launch_skill_defines_gh_app_installation_id_reader() -> None:
    body = _read(LAUNCH_SKILL)
    fn_match = re.search(r"_gh_app_installation_id\(\)\s*\{(.*?)\n\}", body, flags=re.DOTALL)
    assert fn_match, (
        "_gh_app_installation_id() block missing from launch SKILL.md — "
        "T-348 requires both App ID and Installation ID to be read from "
        ".cloglog/config.yaml and exported in launch.sh."
    )
    fn_body = fn_match.group(1)
    assert "import yaml" not in fn_body
    assert "grep '^gh_app_installation_id:'" in fn_body


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


def test_no_operator_host_literals_in_plugin_files() -> None:
    """The operator's App ID and Installation ID are host-specific.

    They live in ``.cloglog/config.yaml`` (this repo's project-local config)
    and are *printed* by ``scripts/preflight.sh`` as a copy-paste hint when
    missing — that script is project-local, not part of the plugin. Inside
    ``plugins/cloglog/`` no file should embed either literal: a downstream
    consumer who installs this plugin into their own repo would otherwise
    get cloglog's bot identity baked into their tooling.
    """
    offenders: list[tuple[Path, int, str, str]] = []
    for path in PLUGIN_ROOT.rglob("*"):
        if not path.is_file():
            continue
        # Skip binary-ish files
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for literal in (OPERATOR_APP_ID, OPERATOR_INSTALLATION_ID):
            if literal in text:
                # Find the offending line for a useful failure message.
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if literal in line:
                        offenders.append((path, lineno, literal, line.strip()))
                        break
    assert not offenders, (
        "Operator-host-specific GitHub App IDs found in plugin files. "
        "These belong in the project-local .cloglog/config.yaml only — "
        "shipping them inside plugins/cloglog/ leaks one operator's bot "
        "identity into every downstream repo that installs the plugin.\n"
        + "\n".join(
            f"  {p.relative_to(REPO_ROOT)}:{ln}: {literal!r} in {snippet!r}"
            for p, ln, literal, snippet in offenders
        )
    )


def test_config_yaml_carries_gh_app_keys() -> None:
    """The project's own .cloglog/config.yaml must have both keys set.

    This is a project-local pin (cloglog's own config), not a plugin pin.
    Without this, every worktree launched from this repo lands with empty
    GH_APP_* and the bot-push flow falls back to anonymous.
    """
    cfg = REPO_ROOT / ".cloglog/config.yaml"
    text = _read(cfg)
    assert re.search(r"^gh_app_id:\s*\"?\d+\"?\s*$", text, flags=re.MULTILINE), (
        ".cloglog/config.yaml must define gh_app_id — see T-348."
    )
    assert re.search(r"^gh_app_installation_id:\s*\"?\d+\"?\s*$", text, flags=re.MULTILINE), (
        ".cloglog/config.yaml must define gh_app_installation_id — see T-348."
    )
