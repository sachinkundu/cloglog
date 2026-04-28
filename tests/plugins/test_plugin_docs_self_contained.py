"""Pin tests: T-315.

The plugin ships docs that skills reference so any project installing the plugin
has access to the lifecycle and credentials specs without needing cloglog's own
docs/ tree.

Pins:
- The three docs exist under plugins/cloglog/docs/.
- No plugin skill/agent/template/hook still cites the bare docs/ paths (absence pin).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugins/cloglog"
PLUGIN_DOCS = PLUGIN_ROOT / "docs"


# ---------------------------------------------------------------------------
# Presence pins — docs must be shipped inside the plugin
# ---------------------------------------------------------------------------


def test_agent_lifecycle_doc_in_plugin() -> None:
    doc = PLUGIN_DOCS / "agent-lifecycle.md"
    assert doc.exists(), (
        f"{doc} is missing — copy docs/design/agent-lifecycle.md into "
        "plugins/cloglog/docs/ so the plugin is self-contained."
    )


def test_setup_credentials_doc_in_plugin() -> None:
    doc = PLUGIN_DOCS / "setup-credentials.md"
    assert doc.exists(), (
        f"{doc} is missing — copy docs/setup-credentials.md into "
        "plugins/cloglog/docs/ so the plugin is self-contained."
    )


def test_two_stage_pr_review_doc_in_plugin() -> None:
    doc = PLUGIN_DOCS / "two-stage-pr-review.md"
    assert doc.exists(), (
        f"{doc} is missing — copy docs/design/two-stage-pr-review.md into "
        "plugins/cloglog/docs/ so the plugin is self-contained."
    )


# ---------------------------------------------------------------------------
# Absence pins — plugin sources must NOT cite the bare docs/ paths
# ---------------------------------------------------------------------------

_PLUGIN_SOURCES = (
    list(PLUGIN_ROOT.rglob("*.md"))
    + list(PLUGIN_ROOT.rglob("*.sh"))
    + list(PLUGIN_ROOT.rglob("*.py"))
)


def _violations(forbidden_pattern: str) -> list[str]:
    """Return lines in plugin sources that contain forbidden_pattern."""
    hits: list[str] = []
    for path in _PLUGIN_SOURCES:
        rel = str(path.relative_to(REPO_ROOT))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if forbidden_pattern in line:
                hits.append(f"  {rel}:{lineno}: {line.strip()!r}")
    return hits


def test_no_bare_agent_lifecycle_path_in_plugin() -> None:
    """No plugin file should reference the bare docs/design/agent-lifecycle.md path.

    The plugin must use plugins/cloglog/docs/agent-lifecycle.md instead so it
    works when installed in any project.
    """
    violations = _violations("docs/design/agent-lifecycle.md")
    assert not violations, (
        "The following plugin files still reference docs/design/agent-lifecycle.md. "
        "Update them to plugins/cloglog/docs/agent-lifecycle.md:\n" + "\n".join(violations)
    )


def test_no_bare_setup_credentials_path_in_plugin() -> None:
    """No plugin file should reference the bare docs/setup-credentials.md path."""
    violations = _violations("docs/setup-credentials.md")
    # Allow occurrences that are already prefixed with plugins/cloglog/
    real_violations = [
        v for v in violations if "plugins/cloglog/docs/setup-credentials.md" not in v
    ]
    assert not real_violations, (
        "The following plugin files still reference docs/setup-credentials.md. "
        "Update them to plugins/cloglog/docs/setup-credentials.md:\n" + "\n".join(real_violations)
    )


def test_no_bare_two_stage_pr_review_path_in_plugin() -> None:
    """No plugin file should reference the bare docs/design/two-stage-pr-review.md path."""
    violations = _violations("docs/design/two-stage-pr-review.md")
    assert not violations, (
        "The following plugin files still reference docs/design/two-stage-pr-review.md. "
        "Update them to plugins/cloglog/docs/two-stage-pr-review.md:\n" + "\n".join(violations)
    )
