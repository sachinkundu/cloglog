"""T-395 pin: ``ALLOW_MAIN_COMMIT=1 git commit`` must appear in close-wave
Step 13 (the only approved use) and must NOT appear in any other plugin
SKILL.md.

The dev-clone pre-commit hook rejects commits on ``main`` without
``ALLOW_MAIN_COMMIT=1``. Close-wave Step 13 is the only SKILL permitted to
set that override — emergency-rollback cherry-picks are the other approved
use, but those are operator shell commands, not SKILL prose. Any other
SKILL that adopts this pattern silently bypasses the PR flow for future
agents who follow it literally.

Silent-failure shape: a PR edits a SKILL in isolation, adds
``ALLOW_MAIN_COMMIT=1 git commit``, and ci.yml's ``paths:`` filter
excludes ``plugins/**`` — the regression ships green. This pin catches
that before merge.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_ROOT = REPO_ROOT / "plugins/cloglog/skills"

# The one SKILL.md permitted to use ALLOW_MAIN_COMMIT=1 git commit.
APPROVED_SKILL = "close-wave/SKILL.md"

# All other SKILL.md files must NOT contain this exact string.
OVERRIDE_PATTERN = "ALLOW_MAIN_COMMIT=1 git commit"


def _all_skill_files() -> list[Path]:
    return sorted(SKILLS_ROOT.rglob("SKILL.md"))


def test_close_wave_skill_has_allow_main_commit() -> None:
    """Positive pin: close-wave SKILL.md Step 13 must use ALLOW_MAIN_COMMIT=1."""
    approved = SKILLS_ROOT / APPROVED_SKILL
    assert approved.exists(), f"Approved SKILL.md not found: {approved}"
    body = approved.read_text(encoding="utf-8")
    assert OVERRIDE_PATTERN in body, (
        f"close-wave SKILL.md must contain `{OVERRIDE_PATTERN}` in Step 13 "
        "for the direct-to-main wave-fold commit. Without it the dev-clone "
        "pre-commit hook rejects the commit with no visible escape hatch."
    )


def test_other_skills_do_not_use_allow_main_commit() -> None:
    """Absence pin: no other SKILL.md may contain ALLOW_MAIN_COMMIT=1 git commit.

    To add a new approved use site, update this test's exemption list and
    add an entry to docs/invariants.md § ALLOW_MAIN_COMMIT.
    """
    approved_relative = APPROVED_SKILL
    violations = []
    for skill_file in _all_skill_files():
        relative = skill_file.relative_to(SKILLS_ROOT).as_posix()
        if relative == approved_relative:
            continue  # the one approved use site
        body = skill_file.read_text(encoding="utf-8")
        if OVERRIDE_PATTERN in body:
            violations.append(relative)

    assert not violations, (
        f"The following SKILL.md files contain `{OVERRIDE_PATTERN}` but are "
        "not in the approved list. Either (a) remove the override and use the "
        "standard wt-* branch + PR flow, or (b) add an exemption to this test "
        "AND an entry to docs/invariants.md § ALLOW_MAIN_COMMIT explaining why "
        "the carve-out is safe.\n"
        f"Violations: {violations}"
    )
