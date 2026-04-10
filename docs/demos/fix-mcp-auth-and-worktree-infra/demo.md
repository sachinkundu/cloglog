# Demo: MCP Auth & Worktree Infrastructure Fix

## 1. MCP Agent Registration Works

Before this fix, `register_agent` returned 401 on every call. Now it succeeds,
returning `project_id` directly and always rotating `agent_token`:

    register_agent(worktree_path="/home/sachin/code/cloglog")
    → worktree_id: f0765795-..., project_id: 4d9e825a-..., agent_token: 8bd279c9...

## 2. Heartbeat Works After Reconnect

Previously, reconnecting agents got agent_token=null and heartbeats failed with 401.
Now tokens rotate on every registration so heartbeats succeed immediately.

## 3. Worktree Infrastructure Setup Succeeds

Before: create-worktree.sh silently failed at DB creation (exit code 2, wrong PG credentials).
After: clean exit 0 with database, migrations, and .env written.

## 4. Pydantic Accepts Worktree .env

Before: make quality failed in worktrees because pydantic rejected unknown env vars.
After: extra="ignore" in Settings allows worktree-specific vars.

## 5. Test Suite

354 passed, 0 failed, 1 xfailed.
