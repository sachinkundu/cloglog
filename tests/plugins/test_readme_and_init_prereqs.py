"""Pin tests: T-318.

README.md must document the plugin install flow and operator prerequisites.
init SKILL.md must have a Prerequisites section before Step 1.

These tests assert:
1. README.md exists at the project root.
2. README.md documents the plugin install path (claude plugins install).
3. README.md lists the backend as a prerequisite.
4. README.md documents /cloglog init quick start.
5. init SKILL.md has a ## Prerequisites section.
6. Prerequisites section mentions plugin install.
7. Prerequisites section mentions DASHBOARD_SECRET (needed for Step 2 bootstrap).
8. Prerequisites section mentions the backend.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
README = REPO_ROOT / "README.md"
INIT_SKILL = REPO_ROOT / "plugins/cloglog/skills/init/SKILL.md"


def _read_readme() -> str:
    assert README.exists(), (
        "README.md not found at repo root — T-318 requires it to document the "
        "plugin install flow and operator prerequisites."
    )
    return README.read_text(encoding="utf-8")


def _read_init_skill() -> str:
    assert INIT_SKILL.exists(), f"{INIT_SKILL} missing"
    return INIT_SKILL.read_text(encoding="utf-8")


def _prereqs_section(body: str) -> str:
    """Extract the Prerequisites section from the init skill."""
    lines = body.splitlines()
    in_prereqs = False
    prereqs_lines: list[str] = []
    for line in lines:
        if line.startswith("## Prerequisites"):
            in_prereqs = True
            prereqs_lines.append(line)
            continue
        if in_prereqs:
            if line.startswith("## ") and not line.startswith("## Prerequisites"):
                break
            prereqs_lines.append(line)
    return "\n".join(prereqs_lines)


# ---------------------------------------------------------------------------
# README.md — presence and content
# ---------------------------------------------------------------------------


def test_readme_exists() -> None:
    """README.md must exist at the project root."""
    _read_readme()  # assertion inside


def test_readme_mentions_plugin_install() -> None:
    """README.md must document the claude plugins install command."""
    body = _read_readme()
    assert "plugins install" in body, (
        "README.md must document 'claude plugins install' so operators know "
        "how to install the cloglog plugin before running /cloglog init."
    )


def test_readme_mentions_backend_prerequisite() -> None:
    """README.md must list the cloglog backend as a prerequisite."""
    body = _read_readme()
    assert "backend" in body.lower(), (
        "README.md must mention the cloglog backend as a prerequisite — "
        "operators need it running before /cloglog init can bootstrap a project."
    )


def test_readme_mentions_cloglog_init() -> None:
    """README.md must document the /cloglog init quick start."""
    body = _read_readme()
    assert "/cloglog init" in body, (
        "README.md must show '/cloglog init' in the quick start section so "
        "operators know how to onboard a new project."
    )


def test_readme_mentions_dashboard_secret() -> None:
    """README.md must mention DASHBOARD_SECRET as a prerequisite."""
    body = _read_readme()
    assert "DASHBOARD_SECRET" in body, (
        "README.md must mention DASHBOARD_SECRET — it is required by Step 2 of "
        "/cloglog init to bootstrap a project on the backend."
    )


# ---------------------------------------------------------------------------
# init SKILL.md — Prerequisites section
# ---------------------------------------------------------------------------


def test_init_skill_has_prerequisites_section() -> None:
    """init SKILL.md must have a ## Prerequisites section."""
    body = _read_init_skill()
    assert "## Prerequisites" in body, (
        "plugins/cloglog/skills/init/SKILL.md must have a ## Prerequisites "
        "section listing what the operator needs before running /cloglog init."
    )


def test_prerequisites_section_before_step1() -> None:
    """Prerequisites section must appear before ## Step 1."""
    body = _read_init_skill()
    prereqs_pos = body.find("## Prerequisites")
    step1_pos = body.find("## Step 1")
    assert prereqs_pos != -1, "## Prerequisites section not found"
    assert step1_pos != -1, "## Step 1 not found"
    assert prereqs_pos < step1_pos, (
        "## Prerequisites must appear before ## Step 1 in init SKILL.md — "
        "operators need to satisfy prerequisites before the skill starts running."
    )


def test_prerequisites_mentions_plugin_install() -> None:
    """Prerequisites section must document plugin installation."""
    prereqs = _prereqs_section(_read_init_skill())
    assert prereqs, "## Prerequisites section not found in init SKILL.md"
    assert "plugins install" in prereqs, (
        "The Prerequisites section must document 'claude plugins install' "
        "so operators know the plugin must be installed before /cloglog init."
    )


def test_prerequisites_mentions_dashboard_secret() -> None:
    """Prerequisites section must mention DASHBOARD_SECRET."""
    prereqs = _prereqs_section(_read_init_skill())
    assert prereqs, "## Prerequisites section not found in init SKILL.md"
    assert "DASHBOARD_SECRET" in prereqs, (
        "The Prerequisites section must mention DASHBOARD_SECRET — Step 2 of "
        "the init skill reads it to authenticate the project bootstrap call."
    )


def test_prerequisites_mentions_backend() -> None:
    """Prerequisites section must mention the backend as a prerequisite."""
    prereqs = _prereqs_section(_read_init_skill())
    assert prereqs, "## Prerequisites section not found in init SKILL.md"
    assert "backend" in prereqs.lower(), (
        "The Prerequisites section must mention that the cloglog backend must "
        "be running — init Step 2 makes a direct HTTP call to it."
    )
