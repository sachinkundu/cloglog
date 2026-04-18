# Agents moving a task to review are now told to watch their inbox for webhook events, not to start a 5-minute polling loop.

*2026-04-18T17:53:22Z by Showboat 0.6.1*
<!-- showboat-id: 50dfee15-493b-463f-9441-41ff9f6cc92a -->

## 1. New MCP tool response text

The MCP server's `update_task_status` tool returns a guidance string to the
agent after moving a task to `review`. We call the tool handler with a mock
HTTP client (no live backend) and print the response body verbatim, so the
exact text the agent will see is captured below.

`mcp-server/scripts/demo-update-task-status.mjs` is a thin harness built
for this demo — it wires a mocked `CloglogClient` to `createServer`,
invokes the `update_task_status` tool with `status=review` and a
sample PR URL, and prints the single text block.

```bash
node mcp-server/scripts/demo-update-task-status.mjs
```

```output
Task demo-task-id moved to review.

CRITICAL — PR #99 is now tracked via GitHub webhooks. Do NOT start a /loop polling cycle. Keep your inbox monitor running; events arrive as JSON lines appended to your inbox file:

- {"type":"review_submitted",...}  → reviewer submitted a review. Move task back to in_progress, address the feedback, push a fix, move back to review.
- {"type":"review_comment",...}    → reviewer posted a standalone inline diff comment (path+line in payload). Same flow as review_submitted.
- {"type":"issue_comment",...}     → reviewer posted an issue-style PR comment. Read the body; if it requires code changes, apply the same in_progress → fix → review flow. Otherwise reply and stay in review.
- {"type":"ci_failed",...}         → a CI check terminated with non-success. Use the github-bot skill to read the failed logs and push a fix. (Note: conclusion=null means still pending — verify with gh pr checks.)
- {"type":"pr_merged","pr_number":99,...}  → PR merged. Call mark_pr_merged with your active task_id (the event does NOT include task_id), then call report_artifact (for spec/plan tasks), then call get_my_tasks and start the next task.

See the github-bot skill's "PR Event Inbox" section for payload details. Webhook delivery is sub-second — no polling needed. Continue with other work or wait for the next inbox event.
```

## 2. The old `/loop 5m` instruction is gone

Before this change the response contained a `/loop 5m Check PR #…`
instruction. Grep confirms no such line is produced any more — neither in
the server source nor in the github-bot skill.

```bash
echo 'server.ts mentions of /loop 5m:' && grep -c '/loop 5m' mcp-server/src/server.ts || true
```

```output
server.ts mentions of /loop 5m:
0
```

```bash
echo 'SKILL.md mentions of /loop 5m (expect 0):' && grep -c '/loop 5m' plugins/cloglog/skills/github-bot/SKILL.md || true
```

```output
SKILL.md mentions of /loop 5m (expect 0):
0
```

```bash
echo 'test suite mentions of /loop 5m (should appear only in a NOT-contain assertion):' && grep -n '/loop 5m' mcp-server/tests/server.test.ts || true
```

```output
test suite mentions of /loop 5m (should appear only in a NOT-contain assertion):
170:    expect(text).not.toContain('/loop 5m')
```

## 3. Rewritten `github-bot` skill

The post-PR steps and the PR-state section of the skill now tell agents to
keep their inbox `Monitor` running and to respond to webhook events —
`review_submitted`, `ci_failed`, `pr_merged`, `pr_closed` — instead
of starting a `/loop` polling cycle. Rule 5 in the Rules list has also
been reworded so that the "atomic with PR creation" pair is board update
+ inbox monitor, not board update + polling loop.

```bash
awk '/^After creating the PR/,/See \[PR Event Inbox\]/' plugins/cloglog/skills/github-bot/SKILL.md
```

```output
After creating the PR, do these two things in order — both are mandatory, never skip either:

1. **Update the board** — call `mcp__cloglog__update_task_status` to move the active task to `review` with the PR URL.
2. **Confirm your inbox monitor is running** — the webhook pipeline will append PR events to your worktree inbox file (`.cloglog/inbox`). Do NOT start a `/loop` polling cycle; GitHub webhooks deliver review/merge/CI events sub-second. If your `Monitor` on the inbox is no longer live, restart it before walking away from the PR.

These two steps are the **last thing you do** after creating a PR. Do not proceed to other work until the inbox monitor is confirmed running — without it you will miss review comments, CI failures, and merge notifications.

See [PR Event Inbox](#pr-event-inbox) below for how to respond to each event type.
```

```bash
awk '/^### PR Event Inbox/,/\*\*Offline fallback:\*\*/' plugins/cloglog/skills/github-bot/SKILL.md
```

````output
### PR Event Inbox

After moving a task to review, PR state changes arrive as webhook-driven events in your worktree inbox (`.cloglog/inbox`). Do NOT start a `/loop` — the backend's webhook dispatcher appends one JSON line per event, and your `Monitor` reads them in real time.

Each event looks like (shapes below match `_build_message` in `src/gateway/webhook_consumers.py`):

```json
{"type":"review_submitted","pr_url":"...","pr_number":123,"review_state":"changes_requested","reviewer":"sachinkundu","body":"First 500 chars…","message":"Review on PR #123: changes_requested by sachinkundu. ..."}
{"type":"review_comment","pr_url":"...","pr_number":123,"reviewer":"sachinkundu","path":"src/foo.py","line":42,"body":"First 500 chars…","message":"Inline comment on PR #123 by sachinkundu at src/foo.py:42: ..."}
{"type":"issue_comment","pr_url":"...","pr_number":123,"commenter":"sachinkundu","body":"First 500 chars…","message":"Comment on PR #123 by sachinkundu: ..."}
{"type":"ci_failed","pr_url":"...","pr_number":123,"check_name":"quality","conclusion":"failure","message":"CI check 'quality' failure on PR #123. ..."}
{"type":"pr_merged","pr_url":"...","pr_number":123,"message":"PR #123 has been MERGED. ..."}
{"type":"pr_closed","pr_url":"...","pr_number":123,"message":"PR #123 was closed without merging."}
```

Note: `pr_merged` does **not** carry a `task_id` — use the active task_id from your own session state when calling `mark_pr_merged`.

How to respond to each event type:

- **`review_submitted`** — move the task back to `in_progress` via `mcp__cloglog__update_task_status`, read the review body from the event (and fetch the full comments with *Check PR Status* below if needed), address the feedback, push a fix, move back to `review`.
- **`review_comment`** — a reviewer posted a standalone inline diff comment without opening a review. The event carries `path`, `line`, and the comment body. Treat it the same as `review_submitted`: move back to `in_progress`, address the feedback at `path:line`, push a fix, move back to `review`.
- **`issue_comment`** — a reviewer posted an issue-style PR comment. These are often clarifying questions or approvals without a formal review. Read the body; if it requires a code change, follow the same in_progress → fix → review flow. If it is informational (e.g., "LGTM, just waiting on CI"), reply via the *Reply to Review Comments* section and stay in `review`.
- **`ci_failed`** — follow [CI Failure Recovery](#ci-failure-recovery) to read the failed logs and push a fix. CI re-runs automatically on push; a subsequent `check_run` webhook will report the new result. Note: the consumer only filters out `conclusion=success`, so `conclusion=null` (still pending) may surface here — check `gh pr checks <PR_NUM>` before assuming the run terminated.
- **`pr_merged`** — call `mcp__cloglog__mark_pr_merged` with your active task_id, then `mcp__cloglog__report_artifact` for spec/plan tasks, then `mcp__cloglog__get_my_tasks` and `start_task` on the next task. If no tasks remain, `unregister_agent` and exit cleanly.
- **`pr_closed`** — the PR was closed without merging. Move the task back to `in_progress` (or note the closure), ask the main agent for direction if unclear.

If the inbox monitor is not running, events pile up silently in the file and nothing will react to them. Restart it with `Monitor(command="tail -f .cloglog/inbox", persistent=true)` as soon as you notice.

**Crash recovery:** Events are **still appended to your inbox file even if the agent is not running**, as long as the task row already has a `pr_url` — `AgentNotifierConsumer._resolve_agent` looks up the worktree by task.pr_url without filtering on online/offline status (`src/gateway/webhook_consumers.py` + `AgentRepository.get_worktree`). After a crash:

1. Re-register and start the inbox `Monitor` on `.cloglog/inbox`. `tail -f` replays the full file, so any events that arrived while you were down will be delivered as notifications.
2. Also run *Check PR Status* below once — the branch-name fallback path excludes offline worktrees, so events that fired before your task had a `pr_url` set (e.g., the first CI run after `git push` but before `update_task_status`) may have been dropped.

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
````

```bash
grep -n 'Inbox monitor is atomic' plugins/cloglog/skills/github-bot/SKILL.md
```

```output
195:5. **Inbox monitor is atomic with PR creation** — creating a PR without an active `Monitor` on your worktree `.cloglog/inbox` means you'll never see review comments, CI failures, or merge notifications. Webhook events arrive there directly — no `/loop` needed. Board update + inbox monitor are both mandatory after every PR.
```

## 4. Unit tests cover the new behavior

`mcp-server/tests/server.test.ts` has been updated so the existing
"update_task_status includes loop instruction …" test now asserts the
response contains `webhook`, `inbox`, `review_submitted`,
`ci_failed`, `pr_merged` and explicitly does **not** contain
`/loop 5m`. The negative test for non-review statuses also asserts
the absence of `webhook` and `inbox`. All 49 MCP server tests pass.

```bash
cd mcp-server && npx vitest run --reporter=basic tests/server.test.ts >/tmp/vitest-out.txt 2>&1 && grep -E '^(Test Files|     Tests)' /tmp/vitest-out.txt | sed 's/(\([0-9]\+\)ms)//g; s/ [0-9]\+ms\$//'
```

```output
```
