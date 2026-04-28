"""Pin test: T-323.

`plugins/cloglog/` ships as a portable plugin — anyone can `claude plugins
install` it and run `/cloglog init` on their own project. The plugin tree
must therefore not embed cloglog operator-host literals. This test greps
the plugin tree for the strings the audit
(`docs/design/plugin-portability-audit.md` §1, §8) catalogues as host- or
project-specific and fails on regressions.

What this pin catches that T-316 does not
-----------------------------------------
T-316 (`tests/plugins/test_t316_no_hardcoded_literals.py`) pins specific
files for specific literals — reviewer-bot logins in `github-bot/SKILL.md`,
`launch/SKILL.md`, and `auto_merge_gate.py`; `cloglog-webhooks` in five
named files; `cloglog-prod` in `close-wave/SKILL.md`. T-323 widens the
scope so a future skill, hook, or template that picks up one of those
literals (or a new related literal — `cloglog.voxdez.com`,
`/home/sachin/...`) is caught wherever it lands.

Carve-outs
----------
* **Brand surface.** The plugin name (`cloglog`), MCP tool prefix
  (`mcp__cloglog__`), MCP server name (`cloglog-mcp`), and credentials
  path (`~/.cloglog/credentials`) ship with the plugin and identify it
  on the wire. Renaming would break every consumer. NOT pinned here.
* **Reviewer-bot logins in cloglog-architecture design docs.** The two
  reviewer App identities are described in design docs that document
  cloglog's bot architecture (`plugins/cloglog/docs/two-stage-pr-review.md`,
  `plugins/cloglog/docs/setup-credentials.md`). These docs are
  cloglog-specific by content — the audit recommends moving them out of
  the plugin tree in a future phase. Until then, exempt them from the
  reviewer-bot scan but still pin their absence everywhere else.
* **`init/SKILL.md` shows the bot login as an `e.g.` example** in the
  reviewer_bot_logins config snippet. That is documentation by example,
  not a hardcoded consumer — exempt.
* **`.cloglog/launch.sh`.** Not in the plugin tree (it lives at the
  consumer-project's runtime, gitignored, regenerated per-host). The
  T-284 pin in `tests/plugins/test_launch_skill_uses_abs_paths.py`
  inverts the assertion there: placeholders must be resolved AND
  absolute paths must be present.

Echoes the pattern of `tests/test_mcp_json_no_secret.py` — read the file,
substring-match, fail loudly with the recommended fix in the message.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugins" / "cloglog"


def _plugin_files() -> list[Path]:
    """Every text-shaped file under `plugins/cloglog/` (skills, hooks,
    scripts, agents, templates, docs, config). Binary/.git/__pycache__
    excluded by extension filter — only files that would plausibly carry
    a literal are scanned.
    """
    suffixes = {".md", ".py", ".sh", ".json", ".yaml", ".yml", ".ts"}
    out: list[Path] = []
    for path in PLUGIN_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts:
            continue
        if path.suffix.lower() in suffixes:
            out.append(path)
    return out


# ---------------------------------------------------------------------------
# Global absence: these literals must not appear ANYWHERE in plugins/cloglog/
# ---------------------------------------------------------------------------

_GLOBAL_FORBIDDEN = (
    (
        "cloglog.voxdez.com",
        "Cloglog's webhook tunnel host. Read from "
        "`.cloglog/config.yaml: webhook_tunnel_host` (or equivalent) and "
        "let downstream projects point GitHub webhooks at their own host.",
    ),
    (
        "cloglog-webhooks",
        "Cloglog's cloudflared tunnel name. Read from "
        "`.cloglog/config.yaml: webhook_tunnel_name`; pinned per-file by "
        "T-316 (`test_t316_no_hardcoded_literals.py`).",
    ),
    (
        "cloglog-dashboard-dev",
        "Cloglog's dashboard auth key. Read from "
        "`.cloglog/config.yaml: dashboard_key` and reference via "
        "`${DASHBOARD_KEY}` in skill examples.",
    ),
    (
        "../cloglog-prod",
        "Cloglog's dev/prod sibling-clone topology. Read from "
        "`.cloglog/config.yaml: prod_worktree_path`. Downstream projects "
        "do not have a `cloglog-prod` sibling.",
    ),
    (
        "/home/sachin",
        "Operator-host home path. Replace with a generic placeholder "
        "(`<project_root>`, `<operator-host-path>`) or compute at runtime "
        "via `git rev-parse --show-toplevel`.",
    ),
)


@pytest.mark.parametrize("literal,fix", _GLOBAL_FORBIDDEN)
def test_no_global_host_literal(literal: str, fix: str) -> None:
    hits = []
    for path in _plugin_files():
        body = path.read_text(encoding="utf-8", errors="replace")
        if literal in body:
            hits.append(str(path.relative_to(REPO_ROOT)))
    assert not hits, f"Literal {literal!r} found in {len(hits)} plugin file(s): {hits}. Fix: {fix}"


# ---------------------------------------------------------------------------
# Reviewer-bot logins: scoped pin (exempt cloglog-architecture design docs)
# ---------------------------------------------------------------------------

_REVIEWER_BOT_LOGINS = (
    "cloglog-codex-reviewer[bot]",
    "cloglog-opencode-reviewer[bot]",
)

# Files exempted because they document cloglog's bot architecture by name
# (audit §1 row "skills/init/SKILL.md" notes init shows the login as an
# `e.g.` example; the design docs in `plugins/cloglog/docs/` are flagged
# for relocation in a later phase). All other plugin files must reach the
# reviewer login through `.cloglog/config.yaml: reviewer_bot_logins`.
_REVIEWER_BOT_DOC_EXEMPT = frozenset(
    {
        PLUGIN_ROOT / "docs" / "two-stage-pr-review.md",
        PLUGIN_ROOT / "docs" / "setup-credentials.md",
        PLUGIN_ROOT / "docs" / "agent-lifecycle.md",
        PLUGIN_ROOT / "skills" / "init" / "SKILL.md",
    }
)


@pytest.mark.parametrize("login", _REVIEWER_BOT_LOGINS)
def test_no_reviewer_bot_login_outside_design_docs(login: str) -> None:
    hits = []
    for path in _plugin_files():
        if path in _REVIEWER_BOT_DOC_EXEMPT:
            continue
        body = path.read_text(encoding="utf-8", errors="replace")
        if login in body:
            hits.append(str(path.relative_to(REPO_ROOT)))
    assert not hits, (
        f"Reviewer-bot login {login!r} found in non-doc plugin file(s): {hits}. "
        "Read the login from `.cloglog/config.yaml: reviewer_bot_logins` "
        "instead — see T-316 for the config-driven pattern. If a new "
        "design doc legitimately needs to name the login, add it to "
        "_REVIEWER_BOT_DOC_EXEMPT with a comment justifying why."
    )


# ---------------------------------------------------------------------------
# Brand surface — sanity pin (mirror of carve-outs)
# ---------------------------------------------------------------------------


# This pin doesn't *enforce* portability; it locks in the carve-out so a
# future broadened regex that strips brand literals (and would silently
# break every consumer) trips loudly. Mirrors the assertion shape of
# `test_step3_settings_carries_no_host_specific_literals`'s brand check.
def test_brand_surface_intact_in_plugin_tree() -> None:
    """The brand-surface literals must remain present somewhere in the
    plugin tree — they're the on-wire identity. If they all disappear, a
    rename has happened and downstream consumers will break."""
    bodies = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in _plugin_files()
    )
    # `cloglog-mcp` is the MCP server name; it lives in `mcp-server/src/`
    # (outside plugins/cloglog/) — out of scope for this sweep.
    for surface in ("cloglog", "mcp__cloglog__", "~/.cloglog/credentials"):
        assert surface in bodies, (
            f"Brand-surface literal {surface!r} no longer appears anywhere "
            "in plugins/cloglog/. The plugin's on-wire identity is gone — "
            "either a rename is in progress (and this pin must update with "
            "the new name) or the host-literal sweep above broadened too "
            "far and stripped the brand too."
        )
