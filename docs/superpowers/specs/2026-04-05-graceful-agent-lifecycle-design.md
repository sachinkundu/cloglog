# F-19: Graceful Agent Lifecycle & Cleanup

**Date:** 2026-04-05
**Feature:** F-19 Graceful Agent Lifecycle & Cleanup (Epic: Operations & Reliability)

## Problem

When worktree agents are killed, they leave ghost records in the database — showing as "online" or "offline" with no way to recover. The cleanup scripts kill processes without calling unregister. No work logs or learnings are generated. The agent's knowledge dies with its process.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Shutdown mechanism | SIGTERM → SessionEnd hook | Claude Code catches SIGTERM and fires SessionEnd hooks. Standard Unix signaling. |
| Who deregisters | The agent itself, always | Mirrors registration — agent registers itself, agent deregisters itself. |
| Shutdown paths | Two: self-initiated (no more tasks) + externally initiated (SIGTERM) | Both converge on the same cleanup. |
| Artifact handoff | Explicit paths in unregister request and WORKTREE_OFFLINE event | No implicit contracts. The event tells consumers exactly where artifacts are. |
| Worktree record after unregister | Delete from DB | No resurrection of worktrees. Work log and git history preserve the record. |
| Consolidation | Automatic by main agent on WORKTREE_OFFLINE | Mechanical operation, no user input needed. |
| Script consolidation | One script replaces three | `remove-worktree.sh`, `cleanup-wave.sh`, `close-wave.sh` → `manage-worktrees.sh` |

## Two Shutdown Paths

### Path 1: Self-Initiated (Agent Completes All Tasks)

1. Agent completes a task, calls `get_my_tasks`
2. No more tasks in backlog for this worktree
3. Agent generates work log and learnings files in `shutdown-artifacts/` directory
4. Agent calls `POST /agents/unregister-by-path` with artifact paths
5. Backend deletes worktree record, emits `WORKTREE_OFFLINE` with artifact paths
6. Agent exits
7. Main agent receives SSE event → reads artifacts → consolidates to main → removes worktree

### Path 2: Externally Initiated (SIGTERM)

1. Main agent (or user) sends SIGTERM to the worktree agent process
2. Claude Code catches SIGTERM, fires `SessionEnd` hook
3. Hook script generates work log and learnings files
4. Hook script calls `POST /agents/unregister-by-path` with artifact paths
5. Backend deletes worktree record, emits `WORKTREE_OFFLINE` with artifact paths
6. Claude Code process exits
7. Main agent receives SSE event → reads artifacts → consolidates to main → removes worktree

Steps 3-7 are identical in both paths.

## SessionEnd Hook

**File:** `.claude/hooks/agent-shutdown.sh`

**Registered in** `.claude/settings.json` under `SessionEnd`.

**Behavior:**
1. Reads `cwd` from hook input JSON
2. Checks if `cwd` is inside `.claude/worktrees/` — exits early if not (main session, not an agent)
3. Generates `shutdown-artifacts/work-log.md` in the worktree directory:
   - Commits since branching from main (`git log --oneline main..HEAD`)
   - Files changed (`git diff --name-only main..HEAD`)
   - PR info if any (`gh pr list --head {branch} --json number,title,state,url`)
4. Generates `shutdown-artifacts/learnings.md`:
   - Extracts from the session transcript or generates a summary of what was learned
   - Issues encountered, patterns discovered, suggestions for CLAUDE.md
5. Calls `POST /agents/unregister-by-path` with:
   ```json
   {
     "worktree_path": "{cwd}",
     "artifacts": {
       "work_log": "{cwd}/shutdown-artifacts/work-log.md",
       "learnings": "{cwd}/shutdown-artifacts/learnings.md"
     }
   }
   ```

**Note on learnings generation:** The SessionEnd hook is a shell script with a timeout. Generating meaningful learnings requires analyzing the session. The hook should generate what it can from git history and leave a structured template. The main agent can enhance it during consolidation if needed.

## Backend Changes

### New Endpoint: `POST /agents/unregister-by-path`

In `src/agent/routes.py`. Accepts:

```json
{
  "worktree_path": "/path/to/worktree",
  "artifacts": {
    "work_log": "/path/to/work-log.md",
    "learnings": "/path/to/learnings.md"
  }
}
```

Behavior:
1. Look up worktree by path (query by `worktree_path` field)
2. End active session (set status to "ended")
3. Emit `WORKTREE_OFFLINE` event with artifact paths in the event data
4. Delete the worktree record from the DB
5. Delete associated sessions from the DB

Returns 204 on success, 404 if worktree not found.

### Modified: Existing `POST /agents/{worktree_id}/unregister`

Update to also delete the worktree record (not just set offline). Both unregister endpoints converge on the same behavior: end session, emit event, delete record.

### WORKTREE_OFFLINE Event Data

The event now carries artifact paths when available:

```json
{
  "worktree_id": "uuid",
  "worktree_path": "/path/to/worktree",
  "reason": "self_shutdown",
  "artifacts": {
    "work_log": "/path/to/work-log.md",
    "learnings": "/path/to/learnings.md"
  }
}
```

When artifacts are not provided (e.g., old-style unregister without artifacts), the `artifacts` field is null.

## Consolidated Script: `scripts/manage-worktrees.sh`

Replaces `remove-worktree.sh`, `cleanup-wave.sh`, and `close-wave.sh`.

### Interface

```bash
# Remove worktrees (single or batch)
./scripts/manage-worktrees.sh remove wt-board [wt-frontend ...]

# Close a wave (remove + work log from git + update main)
./scripts/manage-worktrees.sh close <wave-name> wt-board [wt-frontend ...]
```

### Behavior

**`remove` mode:**
1. For each worktree: `git worktree remove --force`
2. Delete local branch
3. Delete remote branch if merged
4. Summary of what was removed

**`close` mode:**
1. Generate wave work log from git history (same as current `close-wave.sh`)
2. Run `remove` steps for all worktrees
3. `git checkout main && git pull origin main`
4. Print next steps

The script does NOT:
- Kill processes (the agent should already be gone)
- Call any APIs (the agent already unregistered)
- Check for uncommitted changes (the agent should have committed everything)

If a worktree directory doesn't exist, it skips it with a message (idempotent).

### Old Scripts

Delete `scripts/remove-worktree.sh`, `scripts/cleanup-wave.sh`, `scripts/close-wave.sh`. Update CLAUDE.md references.

## Main Agent Consolidation

When the main agent receives a `WORKTREE_OFFLINE` event with artifacts:

1. Read `work_log` from the path in the event data
2. Copy to `docs/superpowers/work-logs/{date}-{worktree-name}.md`
3. Read `learnings` from the path in the event data
4. Merge relevant learnings into `CLAUDE.md` Agent Learnings section
5. Commit the consolidated artifacts to main
6. Run `./scripts/manage-worktrees.sh remove {worktree-name}` to clean up git

This is guidance for the main agent (in CLAUDE.md), not automated code.

## Heartbeat Timeout (F-10) as Fallback

F-10 (separate feature) provides the safety net: if an agent dies without triggering SessionEnd (OOM kill, power loss, etc.), the heartbeat timeout detects the stale session after 3 minutes and cleans up the DB record. F-19 makes this the exception, not the rule.

## Testing Strategy

### Backend
- Unit test: `unregister-by-path` endpoint resolves worktree, deletes record, emits event with artifacts
- Unit test: existing unregister endpoint now deletes record
- Unit test: WORKTREE_OFFLINE event includes artifact paths when provided
- Integration test: full unregister-by-path flow with session cleanup

### Hook Script
- Test that the hook exits early when cwd is not a worktree
- Test that artifact files are generated with correct content
- Test that the unregister API is called with correct payload

### Consolidated Script
- Test `remove` mode removes worktree and branch
- Test `close` mode generates work log
- Test idempotency (skip already-removed worktrees)

## Files Changed

| File | Change |
|------|--------|
| `src/agent/routes.py` | Add `unregister-by-path` endpoint, modify existing unregister to delete |
| `src/agent/schemas.py` | Add `UnregisterByPathRequest` schema with artifacts field |
| `src/agent/services.py` | Modify unregister to delete worktree record |
| `src/agent/repository.py` | Add `delete_worktree` method, add `get_worktree_by_path` method |
| `.claude/hooks/agent-shutdown.sh` | New SessionEnd hook for agent cleanup |
| `.claude/settings.json` | Register SessionEnd hook |
| `scripts/manage-worktrees.sh` | New consolidated script |
| `scripts/remove-worktree.sh` | Delete |
| `scripts/cleanup-wave.sh` | Delete |
| `scripts/close-wave.sh` | Delete |
| `CLAUDE.md` | Update worktree hygiene section, add consolidation guidance |
| `tests/agent/test_routes.py` or `tests/agent/test_integration.py` | New tests for unregister-by-path |
