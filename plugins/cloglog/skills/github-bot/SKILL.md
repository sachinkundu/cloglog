---
name: github-bot
description: Use for ALL GitHub operations — pushing code, creating PRs, commenting on PRs, checking PR status, replying to review comments, or any gh CLI / git push command. Every GitHub interaction must go through the bot identity, never the user's personal account.
user-invocable: true
---

# GitHub Bot Identity

Every GitHub operation must use the GitHub App bot identity. The user cannot merge their own PRs — all work must appear as authored by the bot.

## Prerequisites

- `scripts/gh-app-token.py` must exist in the project root (or a known location). This script generates a short-lived installation token from the GitHub App's PEM key.
- The PEM key must be at `~/.agent-vm/credentials/github-app.pem`.

## Getting a Bot Token

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)
```

Tokens are valid for ~1 hour. Always get a fresh one at the start of each operation sequence.

## Detecting the Repository

All commands use dynamic repo detection instead of hardcoded repo names:

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
```

## Operations

Every operation below requires `BOT_TOKEN`. Always chain commands in a single shell to avoid token expiry between steps.

### Push + Create PR

#### Pre-PR File Audit (mandatory)

Before staging and committing, review every changed file to ensure it belongs in this PR. Do NOT blindly `git add .` or `git add -A`.

1. Run `git diff --name-only` (unstaged) and `git diff --name-only --cached` (staged) to see all changed files.
2. For each file, ask: **"Did I intentionally modify this file as part of this task?"**
3. Files that are **not related to the task** — e.g., skills, configs, migrations, or code in other bounded contexts that you didn't touch — must be excluded. These are likely dirty state inherited from the worktree creation.
4. Only `git add` the files that are genuinely part of your work. Use explicit file paths, never `git add .` or `git add -A`.
5. If you find unrelated changes that are already committed on this branch (inherited from a dirty worktree), you must `git checkout main -- <file>` to revert those files before creating the PR.

**Red flags** — files that almost certainly don't belong:
- Plugin skills (`plugins/*/skills/*/SKILL.md`) unless your task is about skills
- CLAUDE.md or memory files unless your task is about project config
- Files in a different DDD bounded context than your task's scope
- Lock files, `.env` files, or generated files you didn't intentionally regenerate

If in doubt about a file, leave it out. A missing file is easy to add in a follow-up commit; an unrelated file in a PR creates noise and confusion.

#### Push and Create

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
git remote set-url origin "https://x-access-token:${BOT_TOKEN}@github.com/${REPO}.git"
git push -u origin HEAD
GH_TOKEN="$BOT_TOKEN" gh pr create --title "feat: ..." --body "$(cat <<'EOF'
## Demo

<One-sentence feature description from the stakeholder's view>

Demo document: [`docs/demos/<branch>/demo.md`](docs/demos/<branch>/demo.md)
Re-verify: `uvx showboat verify docs/demos/<branch>/demo.md`

## Tests

...

## Changes

...
EOF
)"
```

Note: `git push` requires `remote set-url` because the `gh` CLI doesn't support push. All other GitHub operations use `GH_TOKEN="$BOT_TOKEN" gh ...`.

After creating the PR, do these two things in order — both are mandatory, never skip either:

1. **Update the board** — call `mcp__cloglog__update_task_status` to move the active task to `review` with the PR URL.
2. **Confirm your inbox monitor is running** — the webhook pipeline will append PR events to your worktree inbox file (`.cloglog/inbox`). Do NOT start a `/loop` polling cycle; GitHub webhooks deliver review/merge/CI events sub-second. If your `Monitor` on the inbox is no longer live, restart it before walking away from the PR.

These two steps are the **last thing you do** after creating a PR. Do not proceed to other work until the inbox monitor is confirmed running — without it you will miss review comments, CI failures, and merge notifications.

See [PR Event Inbox](#pr-event-inbox) below for how to respond to each event type.

### Check PR Status

Use this on demand — after receiving a `review_submitted` inbox event to pull the full comment threads, or after re-registering to reconcile state missed while offline. This is NOT a polling replacement for the webhook inbox; it is a drill-down for details the event message truncates. Check all five sources — merge state, CI, inline comments, issue comments, and review state:

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')

# Merge state
GH_TOKEN="$BOT_TOKEN" gh pr view <PR_NUM> --json state -q .state

# CI status
GH_TOKEN="$BOT_TOKEN" gh pr checks <PR_NUM> --json name,state,conclusion

# Inline review comments (where most feedback lives)
GH_TOKEN="$BOT_TOKEN" gh api repos/${REPO}/pulls/<PR_NUM>/comments \
  --jq '.[] | "\(.id) | \(.path):\(.line) | \(.body[:120])"'

# Issue-style PR comments
GH_TOKEN="$BOT_TOKEN" gh api repos/${REPO}/issues/<PR_NUM>/comments \
  --jq '.[] | "\(.id) | \(.body[:120])"'

# Review state (CHANGES_REQUESTED, APPROVED, etc.)
GH_TOKEN="$BOT_TOKEN" gh api repos/${REPO}/pulls/<PR_NUM>/reviews \
  --jq '.[] | "\(.state) | \(.body[:120])"'
```

### PR Event Inbox

After moving a task to review, PR state changes arrive as webhook-driven events in your worktree inbox (`.cloglog/inbox`). Do NOT start a `/loop` — the backend's webhook dispatcher appends one JSON line per event, and your `Monitor` reads them in real time.

Each event looks like:

```json
{"type":"review_submitted","pr_url":"...","pr_number":123,"review_state":"changes_requested","reviewer":"sachinkundu","body":"First 500 chars…","message":"Review on PR #123: changes_requested by sachinkundu. ..."}
{"type":"ci_failed","pr_url":"...","pr_number":123,"check_name":"quality","conclusion":"failure","message":"CI check 'quality' failure on PR #123. ..."}
{"type":"pr_merged","pr_url":"...","pr_number":123,"task_id":"<uuid>","message":"PR #123 has been MERGED. ..."}
{"type":"pr_closed","pr_url":"...","pr_number":123,"message":"PR #123 was closed without merging."}
```

How to respond to each event type:

- **`review_submitted`** — move the task back to `in_progress` via `mcp__cloglog__update_task_status`, read the review body from the event (and fetch the full comments with *Check PR Status* below if needed), address the feedback, push a fix, move back to `review`.
- **`ci_failed`** — follow [CI Failure Recovery](#ci-failure-recovery) to read the failed logs and push a fix. CI re-runs automatically on push; a subsequent `check_run` webhook will report the new result.
- **`pr_merged`** — call `mcp__cloglog__mark_pr_merged`, then `mcp__cloglog__report_artifact` for spec/plan tasks, then `mcp__cloglog__get_my_tasks` and `start_task` on the next task. If no tasks remain, `unregister_agent` and exit cleanly.
- **`pr_closed`** — the PR was closed without merging. Move the task back to `in_progress` (or note the closure), ask the main agent for direction if unclear.

If the inbox monitor is not running, events pile up silently in the file and nothing will react to them. Restart it with `Monitor(command="tail -f .cloglog/inbox", persistent=true)` as soon as you notice.

**Offline fallback:** Webhooks are dropped for offline agents. If you re-register after a crash, call *Check PR Status* below to reconcile state before resuming.

### Reply to Review Comments

Always reply to comments you address. Do NOT resolve threads — that's the reviewer's decision.

**Important:** The `/pulls/comments/{id}/replies` endpoint only works for standalone diff comments ("Add single comment"). Review comments created via "Start a Review" return 404 on that endpoint. Use an issue-style comment instead to address all review feedback:

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')

# Post a summary reply addressing review comments (works for all comment types)
GH_TOKEN="$BOT_TOKEN" gh api repos/${REPO}/issues/<PR_NUM>/comments \
  -f body="Addressed review feedback in commit abc123:
1. **Comment about X** — Fixed by doing Y
2. **Comment about Z** — Changed to W"

# Reply to a standalone diff comment (only works for non-review comments)
GH_TOKEN="$BOT_TOKEN" gh api repos/${REPO}/pulls/comments/<COMMENT_ID>/replies \
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
5. **Inbox monitor is atomic with PR creation** — creating a PR without an active `Monitor` on your worktree `.cloglog/inbox` means you'll never see review comments, CI failures, or merge notifications. Webhook events arrive there directly — no `/loop` needed. Board update + inbox monitor are both mandatory after every PR.
6. **Use dynamic repo detection** — never hardcode the repository name. Always use `$REPO` derived from `gh repo view` or `git remote`.
7. **Never `git add .` or `git add -A`** — always stage files explicitly by path. Review every changed file against the task scope before staging. Unrelated files in a PR are a review burden and a sign of sloppy worktree hygiene.
