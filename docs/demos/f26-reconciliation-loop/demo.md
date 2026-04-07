# F-26: System Reconciliation Skill

*2026-04-07T08:27:28Z by Showboat 0.6.1*
<!-- showboat-id: a0eb60f0-e7ac-42a6-92fd-89463cbb6666 -->

/reconcile is a user-invocable Claude Code skill that detects drift across the multi-agent system. It replaces the old bash script that made unauthenticated curl calls to the API. The skill uses MCP tools for board/agent operations and git/gh CLI for infrastructure checks.

```bash
cat .claude/skills/reconcile/SKILL.md | head -5
```

```output
---
name: reconcile
description: "Run a system reconciliation check to detect and fix drift between the board, agents, PRs, worktrees, and branches. Use this skill when the user says /reconcile, asks to check system health, wants to find stale agents or orphaned worktrees, or suspects drift between board state and reality."
user-invocable: true
---
```

```bash
test ! -f scripts/reconcile.sh && echo "Old script removed" || echo "ERROR: script still exists"
```

```output
Old script removed
```

```bash
grep -c "reconcile" Makefile || echo "0 — Makefile targets removed"
```

```output
0
0 — Makefile targets removed
```

The skill checks 5 categories: (1) Tasks vs PR state, (2) Agents vs tasks, (3) Worktrees vs branches, (4) Stale branches, (5) Orphaned PRs. All board/agent operations go through MCP tools with proper API key auth.

Access control: every API request must present one of three credentials — agent API key (agents/* only), MCP server (API key + X-MCP-Request, everywhere), or dashboard key (X-Dashboard-Key, non-agent routes). Unauthenticated requests are rejected. See tests/gateway/test_route_isolation.py for 10 test cases covering all paths.
