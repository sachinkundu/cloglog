---
name: github-bot
description: Use this skill for ALL GitHub operations — pushing code, creating PRs, commenting on PRs, checking PR status, replying to review comments, or any gh CLI / git push command. Every GitHub interaction must go through the bot identity, never the user's personal account. Trigger on any git push, gh pr, gh api, or GitHub-related action.
---

# GitHub Bot Identity

Every GitHub operation in this repo must use the GitHub App bot identity. The user cannot merge their own PRs — all work must appear as authored by the bot.

## Getting a Bot Token

The bot token is valid for ~1 hour. Get a fresh one before any GitHub operation:

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests ~/.agent-vm/credentials/gh-app-token.py)
```

## Operations

Every operation below requires `BOT_TOKEN` set first. Chain them in a single shell command to avoid the token expiring between steps.

### Push

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests ~/.agent-vm/credentials/gh-app-token.py)
git remote set-url origin "https://x-access-token:${BOT_TOKEN}@github.com/sachinkundu/cloglog.git"
git push -u origin HEAD
```

### Create PR

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests ~/.agent-vm/credentials/gh-app-token.py)
git remote set-url origin "https://x-access-token:${BOT_TOKEN}@github.com/sachinkundu/cloglog.git"
git push -u origin HEAD
GH_TOKEN="$BOT_TOKEN" gh pr create --title "feat: ..." --body "$(cat <<'EOF'
## Summary
...

## Test plan
...

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

After creating the PR, **immediately update the board** — call `update_task_status` to move the active task to `review` with the PR URL. These are an atomic pair; the PR creation is not complete until the board reflects it.

### Check PR Status

Check merge state, CI, inline review comments, issue comments, and review state — all five:

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests ~/.agent-vm/credentials/gh-app-token.py)

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

### Reply to Review Comments

Always reply to comments you address — the reviewer needs to see which comments were handled without digging through diffs. Do NOT resolve threads — that's the reviewer's decision.

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests ~/.agent-vm/credentials/gh-app-token.py)

# Reply to an inline review comment
GH_TOKEN="$BOT_TOKEN" gh api repos/sachinkundu/cloglog/pulls/comments/<COMMENT_ID>/replies \
  -f body="Fixed — changed X to Y in file.py:42"

# Reply to an issue-style comment
GH_TOKEN="$BOT_TOKEN" gh api repos/sachinkundu/cloglog/issues/<PR_NUM>/comments \
  -f body="Addressed — ..."
```

### CI Failure Recovery

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests ~/.agent-vm/credentials/gh-app-token.py)

# Find the failed run
RUN_ID=$(GH_TOKEN="$BOT_TOKEN" gh run list --branch <BRANCH> --workflow ci.yml -L 1 \
  --json databaseId -q '.[0].databaseId')

# Read the logs
GH_TOKEN="$BOT_TOKEN" gh run view $RUN_ID --log-failed
```

Then fix the issue and push — CI re-triggers automatically.

## Rules

1. **Every `gh` command needs `GH_TOKEN="$BOT_TOKEN"`** — not just `git push`. The `git remote set-url` trick only covers git operations; `gh` CLI uses `GH_TOKEN` independently.
2. **Get a fresh token per batch** — tokens last ~1 hour but always get a fresh one at the start of a GitHub operation sequence.
3. **Never use the user's personal identity** — if `gh api` or `gh pr` runs without `GH_TOKEN`, it falls back to the user's auth. Comments will appear as the user instead of the bot.
4. **Check both comment types** — GitHub has inline review comments (`pulls/<N>/comments`) and issue-style comments (`issues/<N>/comments`). Reviewers primarily use inline comments. Always check both.
