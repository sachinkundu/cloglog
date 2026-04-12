---
name: github-bot
description: Use this skill for ALL GitHub operations — pushing code, creating PRs, commenting on PRs, checking PR status, replying to review comments, or any gh CLI / git push command. Every GitHub interaction must go through the bot identity, never the user's personal account. Trigger on any git push, gh pr, gh api, or GitHub-related action.
---

# GitHub Bot Identity

Every GitHub operation in this repo must use the GitHub App bot identity. The user cannot merge their own PRs — all work must appear as authored by the bot.

## Getting a Bot Token

The token script lives in the repo at `scripts/gh-app-token.py`. The PEM key stays outside the repo at `~/.agent-vm/credentials/github-app.pem`. Tokens are valid for ~1 hour.

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)
```

## Operations

Every operation below requires `BOT_TOKEN`. Always chain commands in a single shell to avoid token expiry between steps.

### Push + Create PR

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)
git remote set-url origin "https://x-access-token:${BOT_TOKEN}@github.com/sachinkundu/cloglog.git"
git push -u origin HEAD
GH_TOKEN="$BOT_TOKEN" gh pr create --title "feat: ..." --body "$(cat <<'EOF'
## Summary
...

## Test plan
...
EOF
)"
```

Note: `git push` requires `remote set-url` because the `gh` CLI doesn't support push. All other GitHub operations use `GH_TOKEN="$BOT_TOKEN" gh ...`.

After creating the PR, **immediately update the board** — call `update_task_status` to move the active task to `review` with the PR URL.

### Check PR Status

Use this when polling for PR review feedback. Check all five sources — merge state, CI, inline comments, issue comments, and review state:

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)

# Merge state
GH_TOKEN="$BOT_TOKEN" gh pr view <PR_NUM> --json state -q .state

# CI status
GH_TOKEN="$BOT_TOKEN" gh pr checks <PR_NUM> --json name,state,conclusion

# Inline review comments (where most feedback lives)
GH_TOKEN="$BOT_TOKEN" gh api repos/sachinkundu/cloglog/pulls/<PR_NUM>/comments \
  --jq '.[] | "\(.id) | \(.path):\(.line) | \(.body[:120])"'

# Issue-style PR comments
GH_TOKEN="$BOT_TOKEN" gh api repos/sachinkundu/cloglog/issues/<PR_NUM>/comments \
  --jq '.[] | "\(.id) | \(.body[:120])"'

# Review state (CHANGES_REQUESTED, APPROVED, etc.)
GH_TOKEN="$BOT_TOKEN" gh api repos/sachinkundu/cloglog/pulls/<PR_NUM>/reviews \
  --jq '.[] | "\(.state) | \(.body[:120])"'
```

### PR Polling Loop

After moving a task to review, set up a polling loop to watch for comments and merge:

```
/loop 5m Check PR #<NUM> for review comments, CI status, and merge state using the github-bot skill. If new comments: move task to in_progress, address feedback, push fix, move back to review. If merged: call report_artifact (for spec/plan tasks), then start next task.
```

The loop runs every 5 minutes. When polling detects new review comments, move the task back to `in_progress` before addressing feedback. After pushing fixes, move it back to `review`.

### Reply to Review Comments

Always reply to comments you address. Do NOT resolve threads — that's the reviewer's decision.

**Important:** The `/pulls/comments/{id}/replies` endpoint only works for standalone diff comments ("Add single comment"). Review comments created via "Start a Review" return 404 on that endpoint. Use an issue-style comment instead to address all review feedback:

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)

# Post a summary reply addressing review comments (works for all comment types)
GH_TOKEN="$BOT_TOKEN" gh api repos/sachinkundu/cloglog/issues/<PR_NUM>/comments \
  -f body="Addressed review feedback in commit abc123:
1. **Comment about X** — Fixed by doing Y
2. **Comment about Z** — Changed to W"

# Reply to a standalone diff comment (only works for non-review comments)
GH_TOKEN="$BOT_TOKEN" gh api repos/sachinkundu/cloglog/pulls/comments/<COMMENT_ID>/replies \
  -f body="Fixed — changed X to Y in file.py:42"
```

### CI Failure Recovery

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)

# Find the failed run
RUN_ID=$(GH_TOKEN="$BOT_TOKEN" gh run list --branch <BRANCH> --workflow ci.yml -L 1 \
  --json databaseId -q '.[0].databaseId')

# Read the logs
GH_TOKEN="$BOT_TOKEN" gh run view $RUN_ID --log-failed
```

Diagnose from the logs, push a fix commit — CI re-triggers automatically on push.

## Rules

1. **Every `gh` command needs `GH_TOKEN="$BOT_TOKEN"`** — `git remote set-url` only covers git operations. The `gh` CLI uses `GH_TOKEN` independently. Without it, commands fall back to the user's personal auth and comments appear as the user.
2. **Get a fresh token per batch** — tokens last ~1 hour but always get a fresh one at the start of a GitHub operation sequence.
3. **Check both comment types** — GitHub has inline review comments (`pulls/<N>/comments`) and issue-style comments (`issues/<N>/comments`). Always check both.
4. **Board update is atomic with PR creation** — creating a PR without updating the board is incomplete.
