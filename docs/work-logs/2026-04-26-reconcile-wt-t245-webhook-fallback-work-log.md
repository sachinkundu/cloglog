# T-245 — Webhook routing fallback to main-agent worktree

PR: https://github.com/sachinkundu/cloglog/pull/223 (merged)

## What shipped

Webhook resolver gains a role-based tertiary fallback: when both `Task.pr_url`
and `Worktree.branch_name` lookups miss, the event routes to the project's
`role='main'` worktree. The legacy `settings.main_agent_inbox_path` env var
remains as a quaternary fallback so deployments that set it but haven't yet
run `/cloglog setup` keep working.

- `worktrees.role` column added (`main` | `worktree`) via Alembic migration
  `a3f1d2c4b5e7`. Backfill keys off the `/.claude/worktrees/` path segment.
- `AgentRepository.get_main_agent_worktree(project_id)` returns the earliest
  `role='main'` row (logs warning when more than one). Status is intentionally
  not filtered — the inbox file lives on disk regardless of process state.
- `AgentService.register` derives the role from the worktree path on every
  (re-)registration via `_derive_worktree_role`.
- `webhook_consumers.AgentNotifierConsumer._resolve_agent` chains:
  1. `find_task_by_pr_url`
  2. `get_worktree_by_branch`
  3. `get_main_agent_worktree(project.id)`
  4. `settings.main_agent_inbox_path` (T-253 compat)
- `agent/routes.py:create_close_off_task` resolves the main-agent worktree
  with the same chain (role-first, settings-fallback).

## Tests

- `tests/gateway/test_webhook_consumers.py` — old T-253 settings-only fallback
  tests rewritten to drive the role column. Four acceptance scenarios pinned
  per spec; legacy env-var compat path pinned as well.
- `tests/gateway/test_webhook_consumers.py::TestGetMainAgentWorktree` and
  `TestRegisterDerivesRole` cover the new repository and service code paths.
- Full suite: 865 passed, 1 xfailed (pre-existing); coverage 88.4%.
- Migration round-trip clean.

## Review

Codex session 1 raised a backward-compat regression — removing the
`MAIN_AGENT_INBOX_PATH` runtime path while keeping it documented in
`.env.example` and `config.py`. Fixed by chaining the settings path as a
quaternary fallback after `get_main_agent_worktree`. Codex session 2 passed
after re-review.
