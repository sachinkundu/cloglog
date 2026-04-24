"""Pin test for the silent-failure invariant:

> Alembic migrations in ``src/alembic/versions/`` must be additive against
> live state. Destructive cleanup (marking agents offline, soft-deleting
> rows, rewriting status columns based on transient probes) belongs in
> ``/cloglog reconcile``, not in migrations that run on every deploy.

The rule lives in ``docs/invariants.md`` § Migrations do not mark live data
offline or soft-delete.

This test is a narrow trip-wire — it scans every migration file for a few
specific destructive shapes that have historically caused incidents.
Legitimate additive backfill (``UPDATE tasks SET task_type = 'spec' WHERE
title LIKE ...`` after adding a new column) is allowed; only the cleanup
patterns below are flagged.

If a future migration genuinely needs to perform one of the flagged
operations as a one-shot repair, add the migration filename to
``ALLOWED_DESTRUCTIVE_MIGRATIONS`` with a comment pointing at the task
that approved it. The review gate is deliberate — an allowlist entry is
visible in code review and in the PR diff.
"""

from __future__ import annotations

import re
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "src" / "alembic" / "versions"

# Destructive SQL shapes that must not appear in upgrade() bodies.
# Each entry is (regex, tables_referenced). We keep the table list
# explicit so `test_destructive_patterns_reference_real_tables` can
# cross-check it against Base.metadata without parsing the regex
# source — codex round 2 on PR #206 caught `agent_sessions` when the
# real table is `sessions`; that bug class stays prevented here
# because every table listed is asserted to exist in the models.
#
# We only scan upgrade() bodies; downgrade() is expected to undo
# additive changes (drop_column etc.) and is never run on deploy.
DESTRUCTIVE_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    # Mark worktrees offline from a probe. The original incident: a
    # migration that set status='offline' on every worktree whose
    # on-disk path was missing — destructive cleanup masquerading as
    # schema work.
    (re.compile(r"UPDATE\s+worktrees\s+SET\s+status", re.IGNORECASE), ("worktrees",)),
    # Rewriting session rows (the table is literally named `sessions`;
    # see src/agent/models.py::Session.__tablename__).
    (re.compile(r"UPDATE\s+sessions\s+SET\s+", re.IGNORECASE), ("sessions",)),
    # Hard delete of user data. Soft-delete via a new column is fine
    # (that's additive); deleting existing rows is a reconcile concern.
    (
        re.compile(r"DELETE\s+FROM\s+(worktrees|sessions|tasks|projects)", re.IGNORECASE),
        ("worktrees", "sessions", "tasks", "projects"),
    ),
)

# Migrations explicitly approved to contain a destructive shape. Each entry
# MUST carry a comment naming the approving task so the allowlist stays
# short and its growth is visible in review.
ALLOWED_DESTRUCTIVE_MIGRATIONS: frozenset[str] = frozenset()


_UPGRADE_BODY = re.compile(
    r"def\s+upgrade\s*\(\s*\)\s*->\s*None\s*:(.*?)(?=^def\s+\w|\Z)",
    re.DOTALL | re.MULTILINE,
)


def _extract_upgrade_body(source: str) -> str:
    """Return only the ``upgrade()`` body. Downgrade destructive ops are
    expected and must not be flagged."""
    match = _UPGRADE_BODY.search(source)
    return match.group(1) if match else ""


def test_destructive_patterns_reference_real_tables() -> None:
    """Self-check: every table named in ``DESTRUCTIVE_PATTERNS`` must be a
    real ``__tablename__`` in the models. Codex round 2 on PR #206 caught
    the exact class of bug this guards against — the regex referenced
    ``agent_sessions`` but the actual table is ``sessions``, so a real
    destructive migration against ``sessions`` would have slipped
    through. Cross-checking against ``Base.metadata`` keeps the pattern
    list honest after table renames."""
    # Import every context's models so their __tablename__ values are
    # registered on Base.metadata before we snapshot the table set.
    import src.agent.models  # noqa: F401, PLC0415
    import src.board.models  # noqa: F401, PLC0415
    import src.document.models  # noqa: F401, PLC0415
    import src.review.models  # noqa: F401, PLC0415
    from src.shared.database import Base  # noqa: PLC0415

    known_tables = set(Base.metadata.tables)
    referenced = {t for _, tables in DESTRUCTIVE_PATTERNS for t in tables}

    unknown = sorted(referenced - known_tables)
    assert not unknown, (
        f"DESTRUCTIVE_PATTERNS references table(s) that do not exist in "
        f"Base.metadata: {unknown}. Either fix the table name to a real "
        f"__tablename__, or remove the pattern if the table was dropped. "
        f"Otherwise the pattern silently guards nothing."
    )


def test_no_destructive_migrations() -> None:
    """Scan every migration file and assert its ``upgrade()`` body contains
    no destructive SQL shapes. Approved exceptions go in
    ``ALLOWED_DESTRUCTIVE_MIGRATIONS`` with a comment."""
    offenders: list[str] = []
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        if path.name in ALLOWED_DESTRUCTIVE_MIGRATIONS:
            continue
        body = _extract_upgrade_body(path.read_text())
        for pat, _tables in DESTRUCTIVE_PATTERNS:
            if pat.search(body):
                offenders.append(f"{path.name}: matches /{pat.pattern}/")

    assert not offenders, (
        "Destructive cleanup found in migration upgrade() bodies. "
        "Move this to /cloglog reconcile, not a migration. If this is "
        "a one-shot repair approved in review, add the filename to "
        "ALLOWED_DESTRUCTIVE_MIGRATIONS with a task reference. See "
        "docs/invariants.md § Migrations do not mark live data offline "
        "or soft-delete.\n\n" + "\n".join(offenders)
    )
