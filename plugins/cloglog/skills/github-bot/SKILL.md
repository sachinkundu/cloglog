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

<Choose ONE of the three variants below, matching what the cloglog:demo skill produced:>

<!-- Variant A — real demo (skill reached Steps 2–6) -->
<One-sentence feature description from the stakeholder's view>

Demo document: [`docs/demos/<branch>/demo.md`](docs/demos/<branch>/demo.md)
Re-verify: `uvx showboat verify docs/demos/<branch>/demo.md`

<!-- Variant B — classifier exemption (skill's Step 1 wrote docs/demos/<branch>/exemption.md) -->
<!--
**No demo — classifier exemption (`docs/demos/<branch>/exemption.md`).**

<one-line paraphrase of the classifier's reasoning>

Re-verify: `bash scripts/check-demo.sh` (recomputes the diff_hash; passes while the exemption is fresh).
-->

<!-- Variant C — static auto-exempt (skill's Step 0 matched the allowlist and wrote nothing) -->
<!--
**No demo — static allowlist auto-exempt.**

Every changed file is developer infrastructure (e.g., `docs/`, `tests/`, `scripts/`, `.claude/`, `plugins/*/skills/`). `bash scripts/check-demo.sh` prints `Docs-only branch — no demo required.`
-->

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

- **`review_submitted`** — first run the [Auto-Merge on Codex Pass](#auto-merge-on-codex-pass) gate; if it returns `merge`, run the merge command and stop here. Otherwise move the task back to `in_progress` via `mcp__cloglog__update_task_status`, read the review body from the event (and fetch the full comments with *Check PR Status* below if needed), address the feedback, push a fix, move back to `review`. (An approval-shaped review from the codex bot that does NOT pass the gate — for example, CI is still pending — is informational; stay in `review` and wait for the next event rather than moving to `in_progress`.)
- **`review_comment`** — a reviewer posted a standalone inline diff comment without opening a review. The event carries `path`, `line`, and the comment body. Treat it the same as `review_submitted`: move back to `in_progress`, address the feedback at `path:line`, push a fix, move back to `review`.
- **`issue_comment`** — a reviewer posted an issue-style PR comment. These are often clarifying questions or approvals without a formal review. Read the body; if it requires a code change, follow the same in_progress → fix → review flow. If it is informational (e.g., "LGTM, just waiting on CI"), reply via the *Reply to Review Comments* section and stay in `review`.
- **`ci_failed`** — follow [CI Failure Recovery](#ci-failure-recovery) to read the failed logs and push a fix. CI re-runs automatically on push; a subsequent `check_run` webhook will report the new result. Note: the consumer only filters out `conclusion=success`, so `conclusion=null` (still pending) may surface here — check `gh pr checks <PR_NUM>` before assuming the run terminated.
- **`pr_merged`** —
    1. **First, emit `pr_merged_notification` to the main inbox (T-262)** so the supervisor sees the merge and any parallel worktree blocked on this PR can unblock without polling `gh pr list`. The `pr_merged` webhook only fans out to the merging worktree's own inbox; this notification is the only signal other agents get. Shape:
       ```bash
       printf '{"type":"pr_merged_notification","worktree":"<wt-name>","worktree_id":"<uuid>","task":"T-NNN","task_id":"<uuid>","pr":"<pr-url>","pr_number":NNN,"ts":"%s"}\n' "$(date -Is)" \
         >> <project_root>/.cloglog/inbox
       ```
    2. Then call `mcp__cloglog__mark_pr_merged` with your active task_id, then `mcp__cloglog__report_artifact` for spec/plan tasks, then `mcp__cloglog__get_my_tasks` and `start_task` on the next task. If `get_my_tasks` returns no `backlog` task, run the full shutdown sequence from `docs/design/agent-lifecycle.md` §2 — generate `shutdown-artifacts/work-log.md` + `shutdown-artifacts/learnings.md`, emit the authoritative `agent_unregistered` event to `<project_root>/.cloglog/inbox` (with absolute paths to both artifacts AND the `prs` map per T-262 — see §2 step 5 for the full shape), then call `unregister_agent` and exit. Do NOT unregister without writing the event first; the SessionEnd hook backstop is best-effort, not a substitute.
- **`pr_closed`** — the PR was closed without merging. Move the task back to `in_progress` (or note the closure), ask the main agent for direction if unclear.

If the inbox monitor is not running, events pile up silently in the file and nothing will react to them. Restart it with `Monitor(command="mkdir -p <WORKTREE_PATH>/.cloglog && touch <WORKTREE_PATH>/.cloglog/inbox && tail -n 0 -F <WORKTREE_PATH>/.cloglog/inbox", persistent=true)` as soon as you notice — **always use the absolute worktree path**, never `tail -f .cloglog/inbox` (relative). The `mkdir`/`touch` prelude is mandatory because `tail -f` on a missing file exits immediately and leaves you monitor-less. `-n 0` (start at end-of-file, deliver only events appended from now on) is the correct semantic: the inbox is append-only for the worktree's lifetime, so replaying historical lines would re-deliver already-handled `pr_merged`/`review_submitted` events and crash `start_task`. `tail -F` (capital) re-opens by name if the file is rotated. The setup/launch skills' dedupe filter matches on the inbox path suffix, but using the same absolute form everywhere is the simplest way to keep `TaskList` reconciliation unambiguous across `/clear` cycles.

**Crash recovery:** Events are **still appended to your inbox file even if the agent is not running**, as long as the task row already has a `pr_url` — `AgentNotifierConsumer._resolve_agent` looks up the worktree by task.pr_url without filtering on online/offline status (`src/gateway/webhook_consumers.py` + `AgentRepository.get_worktree`). The new Monitor starts at end-of-file (`-n 0`) so it does NOT auto-replay events queued during downtime — that is correct for `/clear` (where the previous monitor already processed them) but means a real crash needs explicit reconciliation. After a crash, do all three steps in order:

1. Re-register, then run the dedupe-aware idempotent restart from the launch skill's Inbox section (TaskList → match suffix `<WORKTREE_PATH>/.cloglog/inbox` → reuse / spawn / keep-oldest).
2. **Reconcile PR webhook events** by running *Check PR Status* below — drills into current PR merge state, CI, comments, and reviews via `gh`. The branch-name fallback path also excludes offline worktrees, so events that fired before your task had a `pr_url` set (e.g., the first CI run after `git push` but before `update_task_status`) may have been dropped at the producer side too; this drill-down covers both gaps.
3. **Reconcile control events** — webhook events have a GitHub-side source of truth, but supervisor-driven control lines do NOT and the only durable record is the inbox file itself. `request_shutdown` writes a `{"type":"shutdown"}` line to your worktree inbox (`src/agent/services.py:183-223`) and the DB `shutdown_requested` bit is no longer surfaced on heartbeat (`tests/agent/test_unit.py:1253-1357`), so a missed shutdown means the agent silently resumes work after a crash. Inspect the inbox tail one-shot — `Read` the tail of `<WORKTREE_PATH>/.cloglog/inbox` (e.g., last 50 lines) and grep for any line where `"type"` is `"shutdown"`, `"mcp_tool_error"`, `"resume"`, or other supervisor-issued control messages. Act on each one as if it had just arrived. (A proper offset-tracked replay — analogous to `scripts/wait_for_agent_unregistered.py` — is the durable fix and is filed as follow-up work.)

### Auto-Merge on Codex Pass

After a `review_submitted` inbox event, the worktree agent decides whether to merge its own PR via a four-condition gate (T-295). The gate is implemented as a pure-Python helper; the agent shells out to it, never reproduces the logic inline.

**Conditions (all five must hold):**

1. Reviewer is `cloglog-codex-reviewer[bot]` — the `reviewer` field on the inbox event payload.
2. Review body, `lstrip()`ed, starts with `:pass:` — matches `_APPROVE_BODY_PREFIX` in `src/gateway/review_engine.py`. The bot deliberately never posts with `event="APPROVE"`; body content is the canonical approval marker.
3. No human reviewer's most recent review is `CHANGES_REQUESTED`. Codex always posts as `event="COMMENT"` (`post_review` in `src/gateway/review_engine.py`), so a codex `:pass:` does NOT clear a human's outstanding change request — GitHub still blocks the merge from the human's side, and this gate must too. Computed from `gh api repos/${REPO}/pulls/${PR_NUM}/reviews`, filtered to non-bot users, latest review per author.
4. Every check on `gh pr checks <PR_NUM> --json name,bucket` is `pass` or `skipping`. **Empty rollup also passes** — docs-only spec PRs attach no checks because [`ci.yml`](../../../.github/workflows/ci.yml) filters by `paths:`. Pending or failing → see *When the gate holds* below; do not assume an inbox event will retrigger.
5. The PR does not carry the `hold-merge` label — set via `gh pr edit --add-label hold-merge` when a human wants to override auto-merge for a specific PR. Label REMOVAL fires no webhook the consumer surfaces (see [`src/gateway/webhook.py`](../../../src/gateway/webhook.py): only `opened/synchronize/closed` map through), so removing `hold-merge` does NOT re-run the gate by itself — see *When the gate holds*.

**Invocation:**

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
PR_NUM=<the PR number from the inbox event>

# Compute has_human_changes_requested: latest review per non-bot author,
# True iff any of those latest reviews is in state CHANGES_REQUESTED.
# group_by + map(last) collapses to one row per .user.login, preserving the
# REST API's oldest-first ordering.
HAS_HUMAN_CR=$(GH_TOKEN="$BOT_TOKEN" gh api "repos/${REPO}/pulls/${PR_NUM}/reviews" \
  --jq '[.[] | select(.user.type != "Bot")] | group_by(.user.login) | map(last) | any(.state == "CHANGES_REQUESTED")')

# Labels from `gh pr view`, checks from `gh pr checks` — the latter is the
# ONLY `gh` surface that returns the normalized `bucket` field
# (pass/pending/fail/cancel/skipping). `gh pr view --json statusCheckRollup`
# returns conclusion/status enums in a different shape and the gate would
# always read bucket=null. Empty array is fine — the gate treats no checks
# as green for docs-only PRs.
LABELS=$(GH_TOKEN="$BOT_TOKEN" gh pr view "$PR_NUM" --json labels --jq '[.labels[].name]')
CHECKS=$(GH_TOKEN="$BOT_TOKEN" gh pr checks "$PR_NUM" --json name,bucket 2>/dev/null || echo '[]')

# Assemble with `jq -n` so we can inject every field as a typed argument
# (`--argjson` for already-JSON values, `--arg` for strings). This is the
# only invocation shape that survives `gh pr view --jq` not accepting `--arg`.
PAYLOAD=$(jq -nc \
  --arg reviewer "<reviewer field from inbox event>" \
  --arg body "<body field from inbox event>" \
  --arg has_human_cr "$HAS_HUMAN_CR" \
  --argjson checks "$CHECKS" \
  --argjson labels "$LABELS" \
  '{
    reviewer: $reviewer,
    body: $body,
    checks: $checks,
    labels: $labels,
    has_human_changes_requested: ($has_human_cr == "true")
  }')

REASON=$(printf '%s' "$PAYLOAD" | python3 plugins/cloglog/scripts/auto_merge_gate.py)
GATE_RC=$?

if [[ "$GATE_RC" == "0" ]]; then
  GH_TOKEN="$BOT_TOKEN" gh pr merge "$PR_NUM" --squash --delete-branch
  # The pr_merged webhook fires next; the inbox handler runs the existing
  # mark_pr_merged → report_artifact → get_my_tasks flow.
else
  case "$REASON" in
    human_changes_requested)
      # mcp__cloglog__add_task_note(task_id, "auto-merge skipped: human reviewer has CHANGES_REQUESTED outstanding")
      # Same flow as a normal review_submitted from a human — the task is
      # back in the human's court. Move to in_progress, address the review,
      # push, return to review.
      ;;
    ci_not_green)
      # The webhook consumer ONLY emits ci_failed inbox events (see
      # CI_FAILED_CONCLUSIONS in src/gateway/webhook_consumers.py); a check
      # that turns green produces no event, so "wait for the next event"
      # would deadlock the gate when codex passes before CI terminates.
      # Block synchronously on `gh pr checks --watch` (one process, one
      # handler invocation — NOT a /loop), then re-evaluate the gate
      # exactly once. If CI ends red, fall through to the standard
      # in_progress fix flow.
      GH_TOKEN="$BOT_TOKEN" gh pr checks "$PR_NUM" --watch --interval 30 || true
      HAS_HUMAN_CR=$(GH_TOKEN="$BOT_TOKEN" gh api "repos/${REPO}/pulls/${PR_NUM}/reviews" \
        --jq '[.[] | select(.user.type != "Bot")] | group_by(.user.login) | map(last) | any(.state == "CHANGES_REQUESTED")')
      LABELS=$(GH_TOKEN="$BOT_TOKEN" gh pr view "$PR_NUM" --json labels --jq '[.labels[].name]')
      CHECKS=$(GH_TOKEN="$BOT_TOKEN" gh pr checks "$PR_NUM" --json name,bucket 2>/dev/null || echo '[]')
      PAYLOAD=$(jq -nc \
        --arg reviewer "<reviewer field from inbox event>" \
        --arg body "<body field from inbox event>" \
        --arg has_human_cr "$HAS_HUMAN_CR" \
        --argjson checks "$CHECKS" \
        --argjson labels "$LABELS" \
        '{reviewer: $reviewer, body: $body, checks: $checks, labels: $labels, has_human_changes_requested: ($has_human_cr == "true")}')
      REASON=$(printf '%s' "$PAYLOAD" | python3 plugins/cloglog/scripts/auto_merge_gate.py)
      if [[ "$REASON" == "merge" ]]; then
        GH_TOKEN="$BOT_TOKEN" gh pr merge "$PR_NUM" --squash --delete-branch
      fi
      # If still not_green here, CI ended red — let the existing CI failure
      # flow take over.
      ;;
    hold_label)
      # mcp__cloglog__add_task_note(task_id, "auto-merge skipped: hold-merge label set; clear by manual merge or by pushing a no-op commit")
      # hold-merge is sticky from the agent's side: label-removal does NOT
      # produce an inbox event (only opened/synchronize/closed PR actions do
      # — src/gateway/webhook.py). The human override is cleared by either
      # (a) merging the PR manually, or (b) pushing a commit so a fresh
      # codex review_submitted re-runs this gate.
      ;;
    not_codex_pass|not_codex_reviewer)
      # Not an approval shape — the existing review_submitted in_progress
      # flow takes over.
      ;;
  esac
fi
```

**When the gate holds.** Each hold reason has a specific re-trigger path; do not generalize:

| Reason | Will the gate re-run on its own? | What re-triggers it |
| --- | --- | --- |
| `not_codex_reviewer` | No (this run only) | The next codex `review_submitted` event. |
| `not_codex_pass` | No | A new codex review on the next push (codex re-reviews on `synchronize`). |
| `human_changes_requested` | No | Address the human's review, push a fix — `synchronize` triggers a fresh codex review and re-runs the gate (assuming the human dismisses or supersedes their change request). |
| `ci_not_green` | **Yes — the handler `gh pr checks --watch`s in-line** | Synchronous wait inside the same handler invocation, then a single re-evaluation. CI success does not produce an inbox event. |
| `hold_label` | No | Human action: manual merge OR a push that triggers a fresh codex review. The webhook consumer does not surface label-changed events. |

**Why a pure-Python helper, not inline bash.** Tests pin the four-condition truth table at `tests/test_auto_merge_gate.py`. Reproducing the logic in shell would split the source of truth between the test and the agent. The helper takes JSON in, prints the reason, exits 0/1.

**What the agent must NOT do:**

- Do not parse the review body with regex sprawl. The marker is `:pass:` as a leading prefix after `lstrip()` — that is what the helper checks and what `latest_codex_review_is_approval` checks server-side.
- Do not assume "the next webhook event will re-run the gate" for `ci_not_green` or `hold_label`. Successful CI checks and label changes are NOT bridged to the worktree inbox by `src/gateway/webhook_consumers.py` — see the *When the gate holds* table above for the actual re-trigger paths.
- Do not skip the `has_human_changes_requested` lookup. The gate's *reviewer* field only ratifies that the *triggering* event is the codex bot; the helper relies on `has_human_changes_requested` (computed from `gh api .../reviews`) to enforce that no human's outstanding `CHANGES_REQUESTED` is being silently overridden. Omitting the lookup would let a codex `:pass:` posted after a human request-changes review auto-merge the PR — a regression of the T-295 review fix.

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
