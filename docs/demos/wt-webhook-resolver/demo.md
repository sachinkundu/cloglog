# GitHub issue_comment webhooks no longer crash the AgentNotifierConsumer, and every registered worktree now carries a populated branch_name so the resolver's branch fallback actually works.

*2026-04-19T13:00:55Z by Showboat 0.6.1*
<!-- showboat-id: fb3789f7-b876-4039-8eab-260f033bb6f1 -->

Bug scenario: every issue_comment webhook arrives with an empty head_branch. Live-prod worktrees had branch_name='' (MCP client never sent it), so the resolver's fallback ran WHERE branch_name='' AND status='online' and matched every live worktree at once → sqlalchemy.exc.MultipleResultsFound.

Proof 1 — resolver guard. Seed three online worktrees that all carry the pre-fix empty branch_name, then hand _resolve_agent an issue_comment event whose head_branch=''. Before the fix this raised MultipleResultsFound; now it short-circuits and returns None.

```bash
DATABASE_URL="postgresql+asyncpg://cloglog:cloglog_dev@127.0.0.1:5432/cloglog_wt_webhook_resolver" uv run python docs/demos/wt-webhook-resolver/probe.py seed
```

```output
OK: seeded 3 empty-branch online worktrees
```

```bash
DATABASE_URL="postgresql+asyncpg://cloglog:cloglog_dev@127.0.0.1:5432/cloglog_wt_webhook_resolver" uv run python docs/demos/wt-webhook-resolver/probe.py resolve
```

```output
OK: no agent resolved
```

Proof 2 — belt-and-suspenders. AgentRepository.get_worktree_by_branch itself refuses empty branch_name, so any future caller that forgets the upstream guard still cannot trigger the crash.

```bash
DATABASE_URL="postgresql+asyncpg://cloglog:cloglog_dev@127.0.0.1:5432/cloglog_wt_webhook_resolver" uv run python docs/demos/wt-webhook-resolver/probe.py repo
```

```output
OK: None
```

Proof 3 — branch_name populated on registration. AgentService derives the branch via 'git symbolic-ref --short HEAD' at the worktree path when the caller (the MCP client) does not supply one. Invoking it against this worktree returns the actual branch.

```bash
DATABASE_URL="postgresql+asyncpg://cloglog:cloglog_dev@127.0.0.1:5432/cloglog_wt_webhook_resolver" uv run python docs/demos/wt-webhook-resolver/probe.py derive
```

```output
branch=wt-webhook-resolver
```

Proof 4 — data backfill against the live cloglog DB (main shared instance, not the worktree's isolated DB). After running the Alembic migration, no online worktree row carries an empty branch_name — the data trap is closed.

```bash
PGPASSWORD=cloglog_dev psql -h 127.0.0.1 -U cloglog -d cloglog -tA -c "SELECT count(*) FROM worktrees WHERE status='online' AND (branch_name IS NULL OR branch_name='')"
```

```output
0
```
