# Agents moving a task to review are now told to watch their inbox for webhook events, not to start a 5-minute polling loop.

*2026-04-18T17:36:24Z by Showboat 0.6.1*
<!-- showboat-id: 8b97dec6-fbbc-4078-807f-3b9dbd9072a5 -->

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

- {"type":"review_submitted",...}  → reviewer posted feedback. Move task back to in_progress, address the feedback, push a fix, move back to review.
- {"type":"ci_failed",...}         → a CI check failed. Use the github-bot skill to read the failed logs and push a fix.
- {"type":"pr_merged","pr_number":99,...}  → PR merged. Call mark_pr_merged with the task_id, then call report_artifact (for spec/plan tasks), then call get_my_tasks and start the next task.

Webhook delivery is sub-second — no polling needed. Continue with other work or wait for the next inbox event.
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
167:    expect(text).not.toContain('/loop 5m')
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
````

```bash
grep -n 'Inbox monitor is atomic' plugins/cloglog/skills/github-bot/SKILL.md
```

```output
186:5. **Inbox monitor is atomic with PR creation** — creating a PR without an active `Monitor` on your worktree `.cloglog/inbox` means you'll never see review comments, CI failures, or merge notifications. Webhook events arrive there directly — no `/loop` needed. Board update + inbox monitor are both mandatory after every PR.
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
