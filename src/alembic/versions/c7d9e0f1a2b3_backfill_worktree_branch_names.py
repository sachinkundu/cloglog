"""backfill worktree branch_name via git rev-parse

Fixes the root data condition behind T-254: every live ``worktrees`` row had
``branch_name=''`` because the MCP client never sent one on register, which
caused ``get_worktree_by_branch`` to match every online row at once on empty-
``head_branch`` webhook events (→ ``MultipleResultsFound``).

For each online worktree with an empty ``branch_name``:
    - if ``worktree_path`` exists on disk AND ``git rev-parse --abbrev-ref HEAD``
      yields a non-detached branch, UPDATE ``branch_name``.
    - otherwise (path missing, not a git repo, or detached HEAD), mark the row
      ``status='offline'`` — these are ghost registrations whose worktree is no
      longer reachable from this host. The code fixes still guard against any
      residual empty rows, so failing to resolve here is safe.

Revision ID: c7d9e0f1a2b3
Revises: 8f5c0ee31bb4
Create Date: 2026-04-19
"""

from __future__ import annotations

import logging
import os
import subprocess

from sqlalchemy import text

from alembic import op

revision = "c7d9e0f1a2b3"
down_revision = "8f5c0ee31bb4"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def _resolve_branch(worktree_path: str) -> str:
    """Return the current branch at ``worktree_path`` or ``""`` if unresolvable.

    Mirrors ``AgentService._derive_branch_name`` — kept as a migration-local
    helper so the migration stays importable without dragging service-layer
    dependencies.
    """
    if not worktree_path or not os.path.isdir(worktree_path):
        return ""
    try:
        branch = subprocess.check_output(
            ["git", "-C", worktree_path, "symbolic-ref", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""
    return branch


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        text(
            "SELECT id, worktree_path FROM worktrees "
            "WHERE status = 'online' AND (branch_name IS NULL OR branch_name = '')"
        )
    ).fetchall()

    updated = 0
    orphaned = 0
    for row in rows:
        worktree_id = row[0]
        worktree_path = row[1]
        branch = _resolve_branch(worktree_path)
        if branch:
            bind.execute(
                text("UPDATE worktrees SET branch_name = :branch WHERE id = :id"),
                {"branch": branch, "id": worktree_id},
            )
            updated += 1
            logger.info(
                "[T-254 backfill] worktree=%s path=%s branch=%s",
                worktree_id,
                worktree_path,
                branch,
            )
        else:
            bind.execute(
                text("UPDATE worktrees SET status = 'offline' WHERE id = :id"),
                {"id": worktree_id},
            )
            orphaned += 1
            logger.info(
                "[T-254 backfill] worktree=%s path=%s unresolvable → offline",
                worktree_id,
                worktree_path,
            )

    logger.info(
        "[T-254 backfill] summary: updated=%d orphaned=%d total=%d",
        updated,
        orphaned,
        len(rows),
    )


def downgrade() -> None:
    # Data backfill — cannot restore the prior empty strings without losing
    # information, and leaving the resolved names in place is strictly safer
    # than reverting to the broken state.
    pass
