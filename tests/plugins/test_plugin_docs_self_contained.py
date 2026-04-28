"""Pin tests: T-315.

The plugin ships docs that skills reference so any project installing the plugin
has access to the lifecycle and credentials specs without needing cloglog's own
docs/ tree.

Pins:
- The three docs exist under plugins/cloglog/docs/.
- No plugin skill/agent/template/hook still cites the bare docs/ paths (absence pin).
- Plugin non-doc sources use ${CLAUDE_PLUGIN_ROOT}/docs/ not hardcoded plugins/cloglog/docs/.
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

    The plugin must use ${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md instead so it
    works when installed in any project.
    """
    violations = _violations("docs/design/agent-lifecycle.md")
    assert not violations, (
        "The following plugin files still reference docs/design/agent-lifecycle.md. "
        "Update them to ${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md:\n" + "\n".join(violations)
    )


def test_no_bare_setup_credentials_path_in_plugin() -> None:
    """No plugin file should reference the bare docs/setup-credentials.md path.

    The plugin must use ${CLAUDE_PLUGIN_ROOT}/docs/setup-credentials.md instead so it
    works when installed in any project.

    Filter is applied to the raw line content (not the formatted violation string) so that
    a violation inside plugins/cloglog/docs/setup-credentials.md itself is not silently
    allowed because the filename portion contains /docs/setup-credentials.md.
    """
    hits: list[str] = []
    for path in _PLUGIN_SOURCES:
        rel = str(path.relative_to(REPO_ROOT))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            raw = line.strip()
            if (
                "docs/setup-credentials.md" in raw
                and "${CLAUDE_PLUGIN_ROOT}/docs/setup-credentials.md" not in raw
            ):
                hits.append(f"  {rel}:{lineno}: {raw!r}")
    assert not hits, (
        "The following plugin files still reference docs/setup-credentials.md. "
        "Update them to ${CLAUDE_PLUGIN_ROOT}/docs/setup-credentials.md:\n" + "\n".join(hits)
    )


def test_no_bare_two_stage_pr_review_path_in_plugin() -> None:
    """No plugin file should reference the bare docs/design/two-stage-pr-review.md path."""
    violations = _violations("docs/design/two-stage-pr-review.md")
    assert not violations, (
        "The following plugin files still reference docs/design/two-stage-pr-review.md. "
        "Update them to ${CLAUDE_PLUGIN_ROOT}/docs/two-stage-pr-review.md:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Portability pin — plugin non-doc sources must NOT use repo-relative paths
# ---------------------------------------------------------------------------

# Only non-doc plugin sources: skills, agents, hooks, templates, scripts.
# The docs/ dir may contain internal cross-references between docs.
_PLUGIN_NON_DOC_SOURCES = [p for p in _PLUGIN_SOURCES if PLUGIN_DOCS not in p.parents]


def test_no_hardcoded_plugin_repo_path_in_plugin_sources() -> None:
    """Plugin skills/agents/hooks/templates/scripts must not reference plugins/cloglog/docs/.

    In any project that installs the plugin externally, the runtime path is
    ${CLAUDE_PLUGIN_ROOT}/docs/... — the hardcoded repo-relative path only
    exists in the cloglog dogfood checkout.
    """
    hits: list[str] = []
    for path in _PLUGIN_NON_DOC_SOURCES:
        rel = str(path.relative_to(REPO_ROOT))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "plugins/cloglog/docs/" in line:
                hits.append(f"  {rel}:{lineno}: {line.strip()!r}")
    assert not hits, (
        "Plugin non-doc sources must use ${CLAUDE_PLUGIN_ROOT}/docs/ not "
        "plugins/cloglog/docs/ (the latter only exists in the cloglog dogfood checkout):\n"
        + "\n".join(hits)
    )
