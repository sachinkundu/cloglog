"""Pin tests: T-314.

Skill code blocks must reference vendored scripts via ${CLAUDE_PLUGIN_ROOT}/scripts/<name>
rather than project-relative `scripts/<name>` paths so they work when the plugin
is installed in a project other than cloglog.

These tests assert *absence* of the forbidden bare-path patterns. Per the codebase's
absence-pin discipline, only an absence assert catches a future revert that
re-introduces the project-relative form — a presence assert for the new pattern
alone would survive a document that has both the old and new form present.

Smoke tests for the parametrised gh-app-token.py plugin copy verify the env-var
contract introduced by T-314.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / "plugins/cloglog/skills"
GH_APP_TOKEN_SCRIPT = REPO_ROOT / "plugins/cloglog/scripts/gh-app-token.py"


def _all_skill_bodies() -> dict[str, str]:
    """Return {relative_path: content} for every SKILL.md under plugins/cloglog/skills/."""
    result = {}
    for path in SKILLS_DIR.rglob("SKILL.md"):
        rel = str(path.relative_to(REPO_ROOT))
        result[rel] = path.read_text(encoding="utf-8")
    assert result, f"No SKILL.md files found under {SKILLS_DIR}"
    return result


# ---------------------------------------------------------------------------
# Absence pins — forbidden project-relative paths
# ---------------------------------------------------------------------------


def test_no_bare_gh_app_token_path_in_skills() -> None:
    """No SKILL.md code block should invoke scripts/gh-app-token.py via a
    bare project-relative path. The plugin copy lives at
    ${CLAUDE_PLUGIN_ROOT}/scripts/gh-app-token.py and is the only portable form.
    """
    forbidden = "scripts/gh-app-token.py"
    violations: list[str] = []
    for rel, body in _all_skill_bodies().items():
        # Allow occurrences that are already prefixed with ${CLAUDE_PLUGIN_ROOT}
        for line in body.splitlines():
            if forbidden in line and "${CLAUDE_PLUGIN_ROOT}" not in line:
                violations.append(f"  {rel}: {line.strip()!r}")
    assert not violations, (
        "The following SKILL.md lines reference scripts/gh-app-token.py without the "
        "${CLAUDE_PLUGIN_ROOT} prefix. Use ${CLAUDE_PLUGIN_ROOT}/scripts/gh-app-token.py "
        "so the skill works when the plugin is installed in any project:\n" + "\n".join(violations)
    )


def test_no_bare_wait_for_agent_unregistered_path_in_skills() -> None:
    """No SKILL.md code block should invoke scripts/wait_for_agent_unregistered.py
    via a bare project-relative path.
    """
    forbidden = "scripts/wait_for_agent_unregistered.py"
    violations: list[str] = []
    for rel, body in _all_skill_bodies().items():
        for line in body.splitlines():
            if forbidden in line and "${CLAUDE_PLUGIN_ROOT}" not in line:
                violations.append(f"  {rel}: {line.strip()!r}")
    assert not violations, (
        "The following SKILL.md lines reference scripts/wait_for_agent_unregistered.py "
        "without the ${CLAUDE_PLUGIN_ROOT} prefix. Use "
        "${CLAUDE_PLUGIN_ROOT}/scripts/wait_for_agent_unregistered.py:\n" + "\n".join(violations)
    )


def test_no_bare_install_dev_hooks_path_in_skills() -> None:
    """No SKILL.md code block should reference scripts/install-dev-hooks.sh
    via a bare project-relative path.
    """
    forbidden = "scripts/install-dev-hooks.sh"
    violations: list[str] = []
    for rel, body in _all_skill_bodies().items():
        for line in body.splitlines():
            if forbidden in line and "${CLAUDE_PLUGIN_ROOT}" not in line:
                violations.append(f"  {rel}: {line.strip()!r}")
    assert not violations, (
        "The following SKILL.md lines reference scripts/install-dev-hooks.sh without "
        "the ${CLAUDE_PLUGIN_ROOT} prefix. Use "
        "${CLAUDE_PLUGIN_ROOT}/scripts/install-dev-hooks.sh:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Presence pins — the plugin copies must exist
# ---------------------------------------------------------------------------


def test_gh_app_token_script_vendored() -> None:
    assert GH_APP_TOKEN_SCRIPT.exists(), (
        f"{GH_APP_TOKEN_SCRIPT} is missing — vendor it from scripts/gh-app-token.py "
        "and parametrise APP_ID / INSTALLATION_ID to read from GH_APP_ID / "
        "GH_APP_INSTALLATION_ID env vars."
    )


def test_wait_for_agent_unregistered_script_vendored() -> None:
    p = REPO_ROOT / "plugins/cloglog/scripts/wait_for_agent_unregistered.py"
    assert p.exists(), f"{p} is missing — vendor it from scripts/wait_for_agent_unregistered.py"


def test_install_dev_hooks_script_vendored() -> None:
    p = REPO_ROOT / "plugins/cloglog/scripts/install-dev-hooks.sh"
    assert p.exists(), f"{p} is missing — vendor it from scripts/install-dev-hooks.sh"


# ---------------------------------------------------------------------------
# Smoke tests: parametrised gh-app-token.py env-var contract
# ---------------------------------------------------------------------------


def _run_script(**env_overrides: str) -> subprocess.CompletedProcess[str]:
    """Run the plugin gh-app-token.py script in a subprocess with the given env.

    Uses ``uv run`` so PyJWT[crypto] and requests are available without adding
    them to the project's dev dependencies.
    """
    env = {**os.environ, **env_overrides}
    # Strip any real credentials so the test never accidentally calls GitHub.
    env.pop("GH_APP_ID", None)
    env.pop("GH_APP_INSTALLATION_ID", None)
    env.update(env_overrides)
    return subprocess.run(
        [
            "uv",
            "run",
            "--with",
            "PyJWT[crypto]",
            "--with",
            "requests",
            "python",
            str(GH_APP_TOKEN_SCRIPT),
        ],
        capture_output=True,
        text=True,
        env=env,
    )


def test_gh_app_token_errors_when_gh_app_id_missing() -> None:
    """Missing GH_APP_ID → non-zero exit with a clear message."""
    result = _run_script()
    assert result.returncode != 0, "Expected non-zero exit when GH_APP_ID is missing"
    assert "GH_APP_ID" in result.stderr, (
        f"Expected stderr to mention GH_APP_ID but got: {result.stderr!r}"
    )


def test_gh_app_token_errors_when_gh_app_installation_id_missing() -> None:
    """GH_APP_ID set but GH_APP_INSTALLATION_ID missing → non-zero exit with clear message."""
    result = _run_script(GH_APP_ID="12345")
    assert result.returncode != 0, "Expected non-zero exit when GH_APP_INSTALLATION_ID is missing"
    assert "GH_APP_INSTALLATION_ID" in result.stderr, (
        f"Expected stderr to mention GH_APP_INSTALLATION_ID but got: {result.stderr!r}"
    )


def test_gh_app_token_errors_when_pem_missing() -> None:
    """Both env vars set but PEM file absent → non-zero exit mentioning the PEM path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Point HOME at a temp dir with no github-app.pem.
        result = _run_script(
            GH_APP_ID="12345",
            GH_APP_INSTALLATION_ID="67890",
            HOME=tmpdir,
        )
    assert result.returncode != 0, "Expected non-zero exit when PEM file is missing"
    assert "PEM" in result.stderr or "pem" in result.stderr.lower(), (
        f"Expected stderr to mention the PEM file but got: {result.stderr!r}"
    )


def test_gh_app_token_reads_from_env_vars_not_hardcoded() -> None:
    """The plugin gh-app-token.py must NOT contain hardcoded cloglog App/Installation IDs."""
    content = GH_APP_TOKEN_SCRIPT.read_text(encoding="utf-8")
    # The cloglog-specific hardcoded IDs from the original scripts/gh-app-token.py.
    assert "3235173" not in content, (
        "plugins/cloglog/scripts/gh-app-token.py must not embed the hardcoded "
        "cloglog APP_ID '3235173'. Read it from the GH_APP_ID environment variable."
    )
    assert "120404294" not in content, (
        "plugins/cloglog/scripts/gh-app-token.py must not embed the hardcoded "
        "cloglog INSTALLATION_ID '120404294'. Read it from the GH_APP_INSTALLATION_ID "
        "environment variable."
    )
    assert "GH_APP_ID" in content, (
        "plugins/cloglog/scripts/gh-app-token.py must read the App ID from the "
        "GH_APP_ID environment variable."
    )
    assert "GH_APP_INSTALLATION_ID" in content, (
        "plugins/cloglog/scripts/gh-app-token.py must read the Installation ID from "
        "the GH_APP_INSTALLATION_ID environment variable."
    )
