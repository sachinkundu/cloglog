"""T-384 pin: zellij tab handling in the cloglog plugin uses
``zellij action list-tabs --json`` (a single contract) rather than the
brittle text shapes that preceded it.

The pre-T-384 plugin had three different parsers for the same data:

- ``plugins/cloglog/skills/launch/SKILL.md`` Step 4e captured the focused
  tab id with ``zellij action current-tab-info | awk '/^id:/'``.
- ``plugins/cloglog/hooks/lib/close-zellij-tab.sh`` resolved the target
  tab id with ``zellij action list-tabs | awk '$3 == name'`` and
  separately read ``current-tab-info | awk -F': '`` for the focused tab.
- The launch SKILL diagnostic checklist used
  ``zellij action query-tab-names | grep <wt-name>``.

Each shape was a separate place to drift. ``list-tabs --json`` exposes
``tab_id``, ``name``, and ``active`` per tab in one call — both lookups
collapse into a single jq filter. This pin guards the consolidation.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN = REPO_ROOT / "plugins/cloglog"
HELPER = PLUGIN / "hooks/lib/close-zellij-tab.sh"
LAUNCH = PLUGIN / "skills/launch/SKILL.md"
SETUP = PLUGIN / "skills/setup/SKILL.md"


def _read(path: Path) -> str:
    assert path.exists(), f"{path} missing"
    return path.read_text(encoding="utf-8")


def _plugin_files() -> list[Path]:
    return [p for p in PLUGIN.rglob("*") if p.is_file() and p.suffix in {".sh", ".md"}]


def test_helper_uses_list_tabs_json() -> None:
    body = _read(HELPER)
    assert "list-tabs --json" in body, "close-zellij-tab.sh must parse `list-tabs --json` (T-384)"
    assert "zellij action current-tab-info" not in body, (
        "close-zellij-tab.sh must not call current-tab-info — the active "
        "tab id is on the list-tabs --json payload"
    )


def test_launch_skill_uses_list_tabs_json_for_focused_tab_id() -> None:
    body = _read(LAUNCH)
    # Step 4e captures CURRENT_TAB_ID before opening the new tab.
    assert "list-tabs --json" in body, (
        "launch SKILL Step 4e must read the focused tab id from list-tabs --json (T-384)"
    )
    assert "select(.active)" in body, "launch SKILL Step 4e must select the active tab via .active"
    # The pre-T-384 awk shape is gone.
    assert "awk '/^id:/'" not in body, (
        "launch SKILL must not parse `current-tab-info | awk '/^id:/'` "
        "(T-384 — switched to list-tabs --json)"
    )


def test_no_query_tab_names_grep_in_plugin() -> None:
    """`query-tab-names | grep` was the diagnostic-checklist shape;
    `list-tabs --json | jq` replaces it. Historical mentions in prose
    that don't pipe to grep are allowed (they document the prior bug)."""
    for path in _plugin_files():
        body = path.read_text(encoding="utf-8")
        assert "query-tab-names | grep" not in body, (
            f"{path.relative_to(REPO_ROOT)} contains `query-tab-names | grep`"
            " — replace with `list-tabs --json | jq` (T-384)"
        )


def test_no_awk_id_parsing_in_plugin() -> None:
    """The `awk '/^id:/'` shape on `current-tab-info` is forbidden — it
    was the only consumer of that text format."""
    for path in _plugin_files():
        body = path.read_text(encoding="utf-8")
        assert "awk '/^id:/'" not in body, (
            f"{path.relative_to(REPO_ROOT)} contains `awk '/^id:/'` "
            "— current-tab-info parsing is forbidden, use "
            "`list-tabs --json | jq '.[] | select(.active)'` (T-384)"
        )


def test_new_tab_chained_with_focus_back() -> None:
    """`new-tab` steals focus immediately; the focus-back must chain
    in the same shell command so the supervisor sees no blink."""
    body = _read(LAUNCH)
    # Find the new-tab line that launches the worktree's launch.sh and
    # confirm it's followed by `&& zellij action go-to-tab-by-id` — not
    # broken across separate Bash invocations.
    needle = (
        'zellij action new-tab --name "${WORKTREE_NAME}" -- '
        'bash "${WORKTREE_PATH}/.cloglog/launch.sh" \\\n'
        '  && zellij action go-to-tab-by-id "${CURRENT_TAB_ID}"'
    )
    assert needle in body, (
        "launch SKILL Step 4e must chain `new-tab` and "
        "`go-to-tab-by-id` in a single shell command (T-384). The "
        "two-call form leaves a brief focus-steal window."
    )
