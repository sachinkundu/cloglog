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

## Step 2: Generate work log

Create `docs/superpowers/work-logs/<date>-<wave-name>.md` with:
- For each worktree: commits (`git log --oneline main..HEAD`), files changed (`git diff --name-only main..HEAD`), PR number and title
- Leave "Learnings & Issues" and "State After This Wave" sections for the user to review

## Step 3: Kill agent processes

Find and kill any Claude processes running in the worktree directories. Use `pgrep -f` to find them, `kill` to stop them. Wait 2 seconds, then `kill -9` any survivors. Verify none remain.

## Step 4: Remove worktrees and local branches

For each worktree: `git worktree remove --force <path>` and `git branch -D <branch>`. Verify with `git worktree list`.

## Step 5: Clean remote branches

For each worktree branch, delete the remote branch using the bot identity:
```
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests ~/.agent-vm/credentials/gh-app-token.py)
git push "https://x-access-token:${BOT_TOKEN}@github.com/sachinkundu/cloglog.git" --delete <branch>
```
Skip branches that are already gone.

## Step 6: Update main

```
git checkout main
git pull origin main
```

## Step 7: Complete work log

Review the merged PRs for any review comments or issues. Fill in the "Learnings & Issues" section of the work log with what went wrong and what was learned. Fill in "State After This Wave" with what's now implemented.

## Step 8: Update Agent Learnings

If any new learnings were identified, add them to the "Agent Learnings" section of CLAUDE.md so future agents benefit.

## Step 9: Commit work log and updates

Commit the work log and any CLAUDE.md updates to main using the bot identity. Push as bot.

## Step 10: Summary

Print a summary table showing:
- Each worktree: PR number, status (cleaned), commits count
- Work log location
- New learnings added (if any)
- What's ready for the next wave
