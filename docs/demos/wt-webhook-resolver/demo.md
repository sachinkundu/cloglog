# GitHub issue_comment webhooks no longer crash the AgentNotifierConsumer, and cloglog-mcp (running inside the agent-vm) now derives branch_name at register time so the backend's resolver has the data it needs to route events.

*2026-04-19T13:22:46Z by Showboat 0.6.1*
<!-- showboat-id: 8d87f358-7d4c-4ed9-86f4-b57ddcf2a50f -->

Bug scenario: every issue_comment webhook arrives with an empty head_branch. Live-prod worktrees had branch_name='' (cloglog-mcp used to omit it on register), so the resolver's fallback ran WHERE branch_name='' AND status='online' and matched every live worktree at once → sqlalchemy.exc.MultipleResultsFound.

Architecture note (docs/ddd-context-map.md): cloglog runs on the host, cloglog-mcp runs inside each agent-vm. Worktree paths are VM-local. Branch derivation therefore belongs in the MCP server (which has filesystem access), not the backend. The backend is a pass-through that stores what the MCP sends.

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

Proof 3 — reconnect never wipes a populated branch_name. If a transient MCP-side git probe fails and the next register arrives empty, upsert_worktree keeps the previously-stored name. Prevents regressions that would reopen the empty-branch data trap.

```bash
DATABASE_URL="postgresql+asyncpg://cloglog:cloglog_dev@127.0.0.1:5432/cloglog_wt_webhook_resolver" uv run python docs/demos/wt-webhook-resolver/probe.py reconnect
```

```output
OK: reconnect preserved branch_name
```

Proof 4 — branch_name is derived inside cloglog-mcp. The TypeScript test 'register_agent derives branch_name via git and POSTs both to /agents/register' init-s a real git repo, invokes register_agent, and asserts the request body includes the resolved branch. 54 tests, all pass.

```bash
cd mcp-server && npx vitest run --reporter=json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(f"tests: {d["numPassedTests"]} passed / {d["numTotalTests"]} total")'
```

```output
tests: 54 passed / 54 total
```
