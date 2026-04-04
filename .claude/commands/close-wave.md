Close a wave of worktrees after all PRs are merged.

Auto-detect everything:
1. Run `git worktree list` to find active worktrees (anything beyond the main worktree)
2. If no worktrees exist, tell the user there's nothing to close
3. Determine the wave name by reading existing work logs in `docs/superpowers/work-logs/` to figure out the current phase and wave number (e.g., if `phase-1-wave-1.md` exists, this is `phase-1-wave-2`). If no logs exist, this is `phase-1-wave-1`.
4. Show the user what was detected: wave name, worktree list. Ask for confirmation before proceeding.

Args: $ARGUMENTS — optional override (format: "<wave-name> <worktree1> <worktree2> ..."). Usually not needed since auto-detection handles it.

Execute each step below as a tracked task. Mark each task in_progress when starting and completed when done so the user can see progress in the terminal.

## Step 1: Verify PRs are merged

For each worktree, check if its PR has been merged using `gh pr list --state merged --head <branch>`. If any PR is still open, STOP and tell the user which PRs need to be merged first.

## Step 2: Generate work log (pre-cleanup, while worktrees still exist)

Create `docs/superpowers/work-logs/<date>-<wave-name>.md` with:
- For each worktree: commits (`git log --oneline main..HEAD`), files changed (`git diff --name-only main..HEAD`), PR number and title
- Leave "Learnings & Issues" and "State After This Wave" sections to be filled after integration verification

## Step 3: Kill agent processes

Find and kill any Claude processes running in the worktree directories. Use `pgrep -f` to find them, `kill` to stop them. Wait 2 seconds, then `kill -9` any survivors. Verify none remain.

## Step 4: Close zellij tabs

Use `zellij action query-tab-names` to find any tabs associated with this wave. Close them with `zellij action close-tab-by-id <index>`. Never close the tab you're currently running in.

## Step 5: Remove worktrees and local branches

For each worktree: `git worktree remove --force <path>` and `git branch -D <branch>`. Verify with `git worktree list`.

## Step 6: Clean remote branches

For each worktree branch, delete the remote branch using the bot identity:
```
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests ~/.agent-vm/credentials/gh-app-token.py)
git push "https://x-access-token:${BOT_TOKEN}@github.com/sachinkundu/cloglog.git" --delete <branch>
```
Skip branches that are already gone.

## Step 7: Update main

```
git checkout main
git pull origin main
```

## Step 8: Integration verification — CRITICAL

This is the most important step. After updating main with all merged PRs, verify the system is consistent:

### 8a. Run quality gate
Run `make quality`. If it fails, fix the issues before proceeding. Common problems:
- Import errors from models not being imported
- Lint/format issues from merged code
- Type errors from interface mismatches between contexts

### 8b. Check Alembic migration chain
```
python -m alembic history
```
Verify the migration chain is linear (no branches). If two migrations share the same `down_revision`, fix by chaining them. Run `python -m alembic check` to verify models match migrations.

### 8c. Verify route registration
Check `src/gateway/app.py` and confirm ALL context routers are included (not commented out). Each bounded context with routes.py must have its router registered.

### 8d. Verify auth consistency
Check that agent-facing endpoints require auth (Bearer token) and dashboard-facing endpoints are public. Verify all tests use the same auth mechanism.

### 8e. Run smoke test
Start the backend (`make run-backend &`), then exercise the full workflow via curl:
1. Create project (get API key)
2. Import a plan
3. Get board (verify tasks in backlog)
4. Register agent (with Bearer auth)
5. Start a task
6. Attach a document
7. Complete the task
8. Verify board shows done count updated
9. Unregister agent
Kill the backend after.

### 8f. Fix any issues found
If any of the above fail, fix the code directly on main. These are integration issues that individual worktrees cannot detect. Common fixes:
- Migration chain ordering
- Router registration in app.py
- Auth header consistency
- Model import in test conftest.py

## Step 9: Complete work log

Fill in the "Learnings & Issues" section of the work log with:
- What integration issues were found and fixed in step 8
- What tests passed/failed initially
- What patterns future agents should avoid

Fill in "State After This Wave" with what's now implemented and verified working.

## Step 10: Update Agent Learnings

If integration issues were found, add them to the "Agent Learnings" section of CLAUDE.md so future agents know about:
- Cross-context integration patterns (router registration, migration ordering)
- Auth patterns (which header, how to pass in tests)
- Any new rules for worktree discipline

## Step 11: Update integration test suite

If new contexts or endpoints were added in this wave, add or update tests in `tests/e2e/` that exercise the newly integrated functionality. These tests run on main and verify cross-context composition. The e2e test suite should grow with each wave — it's the safety net that catches what worktree-isolated tests cannot.

## Step 12: Commit everything and push

Commit all fixes, work log, CLAUDE.md updates, and new integration tests to main using the bot identity. Push as bot.

## Step 13: Summary

Print a summary table showing:
- Each worktree: PR number, status (cleaned), commits count
- Integration verification: pass/fail, issues found and fixed
- Work log location
- New learnings added
- New e2e tests added
- What's ready for the next wave
