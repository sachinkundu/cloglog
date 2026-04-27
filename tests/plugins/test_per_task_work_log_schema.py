"""Schema validator for per-task work-log files (T-329).

Any file matching ``shutdown-artifacts/work-log-T-*.md`` in any worktree
must conform to the schema documented in
``plugins/cloglog/agents/worktree-agent.md`` — required frontmatter keys
(task, title, pr, merged_at) and required section headers.

This test has two layers:
1. A fixture-based unit test that exercises the parser against synthetic
   valid and invalid inputs so the validator itself has coverage.
2. A glob scan that validates every real work-log file committed to the
   repo (if any exist). In the typical repo state there are no committed
   work logs (they live in gitignored worktrees), so the glob scan is a
   no-op. When a work log *is* present (e.g. under tests/fixtures/) it
   must pass.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

REQUIRED_FRONTMATTER_KEYS = ("task", "title", "pr", "merged_at")
REQUIRED_SECTIONS = (
    "## What shipped",
    "## Files touched",
    "## Decisions",
    "## Review findings + resolutions",
    "## Learnings",
    "## Residual TODOs",
)


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract YAML frontmatter keys from a markdown file."""
    m = re.match(r"^---\n(.*?)\n---", text, flags=re.DOTALL)
    if not m:
        return {}
    result: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip()
    return result


def _validate_work_log(content: str, path: str) -> list[str]:
    """Return a list of validation errors (empty → valid)."""
    errors: list[str] = []
    fm = _parse_frontmatter(content)
    for key in REQUIRED_FRONTMATTER_KEYS:
        if key not in fm or not fm[key]:
            errors.append(
                f"{path}: frontmatter key '{key}' is missing or empty. "
                f"Required by the per-task work-log schema in "
                f"plugins/cloglog/agents/worktree-agent.md."
            )
    for section in REQUIRED_SECTIONS:
        if section not in content:
            errors.append(
                f"{path}: required section '{section}' is absent. "
                f"All six section headers are mandatory so the next session "
                f"can find the load-bearing 'Residual TODOs' handoff."
            )
    return errors


# ---------------------------------------------------------------------------
# Unit tests for the validator itself
# ---------------------------------------------------------------------------

VALID_WORK_LOG = """\
---
task: T-42
title: Implement foo
pr: https://github.com/owner/repo/pull/99
merged_at: 2026-04-27T12:00:00Z
---
## What shipped
Foo was implemented.

## Files touched
src/foo.py

## Decisions
Used approach A over B because of X.

## Review findings + resolutions
Codex flagged Y; resolved by Z.

## Learnings (candidate for CLAUDE.md)
Always check Y before doing Z.

## Residual TODOs / context the next task should know
The bar feature is blocked on foo being wired up.
"""


def test_valid_work_log_passes() -> None:
    errors = _validate_work_log(VALID_WORK_LOG, "fixture")
    assert errors == [], f"Unexpected validation errors: {errors}"


@pytest.mark.parametrize("missing_key", REQUIRED_FRONTMATTER_KEYS)
def test_missing_frontmatter_key_fails(missing_key: str) -> None:
    # Remove the key from the frontmatter
    content = VALID_WORK_LOG.replace(f"{missing_key}:", f"x_{missing_key}:")
    errors = _validate_work_log(content, "fixture")
    assert any(missing_key in e for e in errors), (
        f"Expected a validation error for missing frontmatter key '{missing_key}' but got: {errors}"
    )


@pytest.mark.parametrize("missing_section", REQUIRED_SECTIONS)
def test_missing_section_fails(missing_section: str) -> None:
    content = VALID_WORK_LOG.replace(missing_section, "## Replaced")
    errors = _validate_work_log(content, "fixture")
    assert any(missing_section in e for e in errors), (
        f"Expected a validation error for missing section '{missing_section}' but got: {errors}"
    )


def test_missing_frontmatter_entirely_fails() -> None:
    content = "# Work log\nNo frontmatter here.\n## What shipped\nFoo.\n"
    errors = _validate_work_log(content, "fixture")
    # All frontmatter keys should be flagged
    assert len(errors) >= len(REQUIRED_FRONTMATTER_KEYS), (
        f"Expected at least {len(REQUIRED_FRONTMATTER_KEYS)} errors for missing "
        f"frontmatter, got {len(errors)}: {errors}"
    )


# ---------------------------------------------------------------------------
# Glob scan: validate any committed work-log files in the repo
# ---------------------------------------------------------------------------


def _find_committed_work_logs() -> list[Path]:
    """Find work-log-T-*.md files tracked in the repo tree.

    These are rare (work logs normally live in gitignored worktrees), but
    any fixture files or accidentally committed logs must pass validation.
    """
    return list(REPO_ROOT.rglob("work-log-T-*.md"))


COMMITTED_LOGS = _find_committed_work_logs()


@pytest.mark.skipif(
    not COMMITTED_LOGS,
    reason="No work-log-T-*.md files found in repo tree — nothing to validate",
)
@pytest.mark.parametrize("log_path", COMMITTED_LOGS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_committed_work_log_schema(log_path: Path) -> None:
    content = log_path.read_text(encoding="utf-8")
    rel = str(log_path.relative_to(REPO_ROOT))
    errors = _validate_work_log(content, rel)
    assert errors == [], "\n".join(errors)
