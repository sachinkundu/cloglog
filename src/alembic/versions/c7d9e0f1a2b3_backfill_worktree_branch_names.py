"""backfill worktree branch_name where the path is host-visible

Context for T-254: every live ``worktrees`` row had ``branch_name=''`` because
the MCP server used to omit it on register, which caused the webhook resolver's
branch fallback to match every online row at once on empty-``head_branch``
events (→ ``MultipleResultsFound``). The primary fix is the MCP server now
derives and sends ``branch_name``; this migration is an opportunistic cleanup
for rows that existed before that rollout.

**Additive-only.** The backend runs on the host and cannot see worktree paths
that live inside agent-vms (``docs/ddd-context-map.md`` — cloglog runs on the
host, worktrees are VM-local). This migration therefore never downgrades a row
to ``offline`` just because the host cannot stat the path — doing so would
silently take legitimate VM-hosted worktrees offline and break their webhook
routing until they re-register. Rows whose path is not reachable from the host
are left untouched; they will self-heal on the next MCP ``register_agent``
call (which carries the correct branch name), and the code-level resolver
guards make leaving them empty safe in the meantime. Ghost-worktree cleanup is
F-48's job (T-220/T-221), not this data migration.

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

    Mirrors ``cloglog-mcp``'s ``deriveBranchName`` — kept as a migration-local
    helper so the migration stays importable without dragging service-layer
    dependencies. Only succeeds when the host process can see the path, which
    is only the single-host dev topology; VM-hosted rows stay untouched.
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
    skipped = 0
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
            # Path not visible to the host (e.g. VM-local) — leave the row
            # alone. The MCP server populates branch_name on next register.
            skipped += 1
            logger.info(
                "[T-254 backfill] worktree=%s path=%s not host-visible, "
                "will self-heal on next register",
                worktree_id,
                worktree_path,
            )

    logger.info(
        "[T-254 backfill] summary: updated=%d skipped=%d total=%d",
        updated,
        skipped,
        len(rows),
    )


def downgrade() -> None:
    # Data-only migration — restoring the prior empty strings would re-open
    # the MultipleResultsFound crash the fix resolves.
    pass
