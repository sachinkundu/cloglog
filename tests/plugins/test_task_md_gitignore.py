"""Pin test: task.md is gitignored at any depth; templates/task.md.template is not.

T-438 fix #4.

The rule in .gitignore:

    task.md
    !plugins/cloglog/templates/task.md.template

prevents worktree agents from accidentally staging the per-launch ``task.md``
file (rendered by the launch SKILL into each worktree root). The un-ignore for
``task.md.template`` keeps the canonical plugin template tracked so the launch
SKILL can render it.

Silent-failure shape: a future .gitignore edit that drops or narrows the
``task.md`` rule would let an agent's ``git add .`` accidentally stage a
per-launch ``task.md`` carrying task UUIDs and worktree state. The test runs
``git check-ignore`` against the real repo so it exercises the full gitignore
rule set (including parent-directory files) rather than parsing the text.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _check_ignored(path: str) -> bool:
    """Return True if git considers path ignored, False otherwise."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    return result.returncode == 0


def test_task_md_is_ignored_at_repo_root() -> None:
    """task.md at the repo root must be gitignored."""
    assert _check_ignored("task.md"), (
        "task.md must be gitignored — the launch SKILL renders it per-launch "
        "and agents must not accidentally stage it. Check .gitignore."
    )


def test_task_md_is_ignored_at_depth() -> None:
    """task.md nested in subdirectories must be gitignored (no leading slash in rule)."""
    assert _check_ignored(".claude/worktrees/wt-example/task.md"), (
        "task.md must be gitignored at any depth — the .gitignore rule must "
        "not be anchored with a leading slash. T-438 fix #4."
    )


def test_task_md_template_is_not_ignored() -> None:
    """plugins/cloglog/templates/task.md.template must NOT be gitignored.

    The template is the canonical source rendered by the launch SKILL and must
    remain tracked. The .gitignore ``!`` un-ignore rule keeps it visible.
    """
    assert not _check_ignored("plugins/cloglog/templates/task.md.template"), (
        "plugins/cloglog/templates/task.md.template must not be gitignored — "
        "the launch SKILL renders this template per-launch and it must stay "
        "tracked. Check .gitignore for a missing or incorrect !un-ignore rule."
    )


def test_gitignore_has_task_md_rule() -> None:
    """The .gitignore file must contain a bare ``task.md`` rule (not anchored)."""
    gitignore = REPO_ROOT / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines()
    assert "task.md" in lines, (
        ".gitignore must contain a bare 'task.md' line (no leading slash) so "
        "the rule matches at any directory depth. T-438 fix #4."
    )


def test_gitignore_has_task_md_template_unignore() -> None:
    """The .gitignore must un-ignore the canonical task.md template."""
    gitignore = REPO_ROOT / ".gitignore"
    text = gitignore.read_text(encoding="utf-8")
    assert "!plugins/cloglog/templates/task.md.template" in text, (
        ".gitignore must un-ignore plugins/cloglog/templates/task.md.template "
        "so the canonical template stays tracked. T-438 fix #4."
    )
