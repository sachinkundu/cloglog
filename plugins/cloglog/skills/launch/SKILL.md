---
name: launch
description: Launch worktree agents for features or tasks. Handles the full lifecycle — clean state check, task resolution, prompt assembly, agent launch with worktree isolation, and zellij tab management.
user-invocable: true
---

# Launch Worktree Agents

Launch isolated agents for features or tasks. Each agent gets its own worktree, runs autonomously, and follows the full pipeline.

**Usage:**
```
/cloglog launch F-12          # launch agent for a feature
/cloglog launch T-45 T-46     # launch agents for standalone tasks
```

Arguments: `$ARGUMENTS` — one or more feature (F-*) or task (T-*) identifiers.

## Step 1: Pre-flight Checks

### 1a. Check for uncommitted changes

Run `git status`. If there are uncommitted changes, STOP and commit or stash them first. Worktrees branch from HEAD and inherit dirty state — agents will see those diffs and think it's their work. This is non-negotiable.

### 1b. Resolve entity IDs

Parse `$ARGUMENTS` to extract feature/task identifiers (F-*, T-*) — `/cloglog launch` only accepts features and standalone tasks; epics (`E-*`) are containers and have no launch semantics in Steps 2-4 or the agent template. For each identifier, call `mcp__cloglog__search` with the entity-number token (e.g. `T-45`, `F-12`) — a single call returns the matching `id`/`type`/`number`/`title`/`status`/`model` (and parent epic + feature for tasks), so you never have to page the full board to turn `T-NNN` into a UUID. For tasks, capture the `model` field — it drives the `--model` flag passed to claude at launch (e.g. `claude-opus-4-7` for reasoning-heavy spec/plan tasks, `claude-sonnet-4-6` for implementation).

Fall back to `mcp__cloglog__get_board` / `mcp__cloglog__list_features` / `mcp__cloglog__get_active_tasks` only when you genuinely need to *enumerate* (e.g. "list every backlog task in this feature") rather than resolve a known number.

**Never `psql` the board** to look up an ID. The MCP server is the only sanctioned read path; raw SQL bypasses the agent-token auth checks and can drift out of sync with the API contract.

### 1c. Check task status

Only launch agents for tasks in `backlog` status. Skip tasks that are already `in_progress`, `review`, or `done`. Warn the user about skipped tasks.

### 1d. Assess conflict risk

If multiple tasks touch the same areas, warn the user about merge conflict risk but proceed if they confirm.

## Step 2: Prepare Pipeline Tasks (Features Only)

For each feature (F-*), ensure the three pipeline tasks exist:

1. **spec** — "Write design spec for F-*"
2. **plan** — "Write implementation plan for F-*"
3. **impl** — "Implement F-*"

Use `mcp__cloglog__create_task` to create any missing pipeline tasks. The state machine guards enforce ordering — the agent cannot start plan until spec is done, cannot start impl until plan is done.

**Model assignment for pipeline tasks:** Assign models when creating tasks — spec and plan are reasoning-heavy and should use `claude-opus-4-7`; impl is mechanical and should use `claude-sonnet-4-6`. Pass `model` to `mcp__cloglog__create_task`. If the task already exists (returned by search), its model field is already set from prior creation and you do not need to update it.

After ensuring all pipeline tasks exist, resolve `TASK_MODEL` for the launch step: call `mcp__cloglog__get_active_tasks` (or re-use the search result from Step 1b) to find the first backlog/in-progress pipeline task for this feature, and capture its `model` field as `TASK_MODEL`. This ensures `TASK_MODEL` is set correctly even for feature launches where Step 1b only resolved the F-* identifier.

For standalone tasks (T-*), skip this step — they are executed directly.

## Step 3: Assemble Agent Prompt

For each task or feature, write an `AGENT_PROMPT.md` to a temporary location. The prompt must include:

### Prompt Template

```markdown
# Agent Prompt

## Task
**<T-number or F-number>: <title>**
Priority: <priority>

## What to Build/Fix
<description from the task or feature>

## Task IDs
- Task ID: `<uuid>`
- Feature ID: `<uuid>` (if applicable)

## Inbox
Monitor your inbox for messages from the main agent. **One inbox monitor per agent process, period** — persistent monitors survive `/clear`, so a naive spawn on a re-entered session would duplicate tails and triple-fire every event.

Before spawning, reconcile against existing monitors:

1. Call `TaskList`.
2. Filter for running Monitor tasks whose `command` ends in `.cloglog/inbox` and resolves to **this** worktree's inbox file. Match on path suffix (`/.cloglog/inbox`) and verify the resolved absolute path equals `<WORKTREE_PATH>/.cloglog/inbox` — historical monitors started with the relative path `tail -f .cloglog/inbox` (see the github-bot crash-recovery flow) must still be caught here, otherwise the dedupe is bypassed and `/clear` followed by recovery would still spawn a duplicate.
3. Branch on the count of matches:
   - **Exactly one** → reuse it; do not spawn a new Monitor.
   - **Zero** → spawn a fresh persistent monitor. **The inbox file may not exist yet** — `.cloglog/on-worktree-create.sh` does not pre-create it, and the lifecycle spec leaves first creation to the backend's first webhook write. `tail -f` on a missing file exits immediately (verified: this skill's own author hit it on session start). Use `tail -n 0 -F` — start at end-of-file (deliver only events appended from now on) and reopen-by-name on rotation. Wrap with `mkdir`/`touch` so the file is materialised first:
     ```
     Monitor(
       command: "mkdir -p <WORKTREE_PATH>/.cloglog && touch <WORKTREE_PATH>/.cloglog/inbox && tail -n 0 -F <WORKTREE_PATH>/.cloglog/inbox",
       description: "Messages from main agent",
       persistent: true
     )
     ```
     **Why `-n 0`, not `-n +1`.** The inbox is append-only for the worktree's lifetime (`src/gateway/webhook_consumers.py` always appends; `request_shutdown` is pinned by `tests/agent/test_unit.py` not to truncate). Replaying from line 1 on a re-entered session would re-deliver already-handled events — and the documented `pr_merged` handler immediately calls `start_task`, which raises if another task is active (`src/agent/services.py:357-370`). To reconcile events that landed while you were offline, use the *Check PR Status* drill-down in `plugins/cloglog/skills/github-bot/SKILL.md`, not `tail` history.
   - **Two or more** → keep the oldest matching monitor and `TaskStop` the rest.

When you receive a message, read it and act on the instruction. The main agent may send rebasing requests, priority changes, or other guidance.

## Workflow
1. Read the project CLAUDE.md for project-specific instructions
2. Load MCP tools: call `ToolSearch(query: "select:mcp__cloglog__register_agent,mcp__cloglog__start_task,mcp__cloglog__update_task_status,mcp__cloglog__get_my_tasks,mcp__cloglog__unregister_agent,mcp__cloglog__add_task_note,mcp__cloglog__mark_pr_merged,mcp__cloglog__report_artifact,mcp__cloglog__search")` — MCP tools are deferred and MUST be loaded via ToolSearch before calling them. `mcp__cloglog__search` is in the preload so any later T-NNN/F-NN reference (and parent-epic context for tasks) can be resolved in one call instead of paging the board.

   **Stop on MCP failure.** Halt on any MCP failure: startup unavailability emits `mcp_unavailable` and exits; runtime tool errors emit `mcp_tool_error` and wait for the main agent; transient network errors get one backoff retry before escalating. See `${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md` §4.1 for both event shapes.
     - **Startup** (ToolSearch returns no matches, or the first MCP call after register fails at the transport layer): write an `mcp_unavailable` event to `<project_root>/.cloglog/inbox` and exit.
     - **Runtime** (MCP tool call returns 5xx, backend exception, 409 state-machine guard, auth rejection, or schema error mid-task): write an `mcp_tool_error` event to `<project_root>/.cloglog/inbox` carrying the failing tool name + error, halt, and wait on your inbox Monitor for main-agent guidance. Never retry a 409 or a 5xx; never fall back to direct HTTP or `gh api`.
     - **Transient network** (`ECONNRESET`, `ETIMEDOUT`, fetch timeout): one retry after ≥ 2 s backoff, then escalate to `mcp_tool_error` on second failure.
3. Start inbox monitor (see Inbox section above)
4. Register: call `mcp__cloglog__register_agent` with this worktree path
5. Echo `agent_started` to the main agent inbox (`<project_root>/.cloglog/inbox`) so the main agent sees you are live:
   ```bash
   printf '{"type":"agent_started","worktree":"<wt-name>","worktree_id":"<uuid>","ts":"%s"}\n' "$(date -Is)" \
     >> <project_root>/.cloglog/inbox
   ```
6. Start task: call `mcp__cloglog__start_task` with the task ID
7. Run existing tests first to establish a green baseline
8. Implement the feature or fix
9. Run the project quality gate
10. Produce proof-of-work demo — invoke the demo skill (`cloglog:demo`).
    The skill classifies the diff and terminates in one of three states:
    a real `docs/demos/<branch>/demo.md` for user-observable changes; a
    committed `docs/demos/<branch>/exemption.md` when the classifier
    returns `no_demo`; or a static auto-exempt (no file written) when
    every changed file is on the developer-infrastructure allowlist. Do
    not pre-decide — let the skill decide.
11. Create PR using the github-bot skill, with the `## Demo` section
    reflecting whichever terminal state the skill reached (the skill's
    own Step 6 prints the matching PR-body template).
12. Move task to review with PR URL via `mcp__cloglog__update_task_status`
13. Your `.cloglog/inbox` Monitor delivers review/merge/CI events automatically — do NOT start a `/loop`. On `review_submitted` from any login listed in `.cloglog/config.yaml: reviewer_bot_logins` (the auto-merge-eligible final-stage reviewers — cloglog ships codex only; opencode stage-A reviews are intentionally not in that list and route through the standard in_progress flow): run the auto-merge gate (see the github-bot skill's *Auto-Merge on Codex Pass* section). On `pr_merged`, run the per-task shutdown sequence:
    - **First**, append a `pr_merged_notification` line to `<project_root>/.cloglog/inbox` so the supervisor sees the merge (T-262 — the `pr_merged` webhook only fans out to the merging worktree's own inbox):
      ```bash
      printf '{"type":"pr_merged_notification","worktree":"<wt-name>","worktree_id":"<uuid>","task":"T-NNN","task_id":"<uuid>","pr":"<pr-url>","pr_number":NNN,"ts":"%s"}\n' "$(date -Is)" \
        >> <project_root>/.cloglog/inbox
      ```
    - Call `mcp__cloglog__mark_pr_merged(task_id, worktree_id)`. For `spec` tasks also call `mcp__cloglog__report_artifact(task_id, worktree_id, artifact_path)`.
    - Write `shutdown-artifacts/work-log-T-<NNN>.md` — structured per-task summary (see the worktree-agent template's **Per-Task Work-Log Schema**). The **Residual TODOs / context the next task should know** section is the load-bearing handoff; write it carefully.
    - Build the aggregate `shutdown-artifacts/work-log.md` by concatenating all `work-log-T-*.md` files in chronological order plus a one-line envelope header (backward compat with close-wave Step 5d).
    - **Emit `agent_unregistered` to `<project_root>/.cloglog/inbox` before `unregister_agent`.** Shape:
      ```json
      {
        "type": "agent_unregistered",
        "worktree": "<wt-name>",
        "worktree_id": "<uuid>",
        "ts": "<utc-iso>",
        "tasks_completed": ["T-NNN"],
        "prs": {"T-NNN": "<pr-url>"},
        "artifacts": {
          "work_log": "/abs/path/shutdown-artifacts/work-log.md",
          "learnings": null
        },
        "reason": "pr_merged"
      }
      ```
      Absolute paths are required. `tasks_completed` is a flat list of task UUIDs; build the `prs` map by calling `mcp__cloglog__get_my_tasks()` and, for each row with a non-null `pr_url`, keying the map at `T-{row.number}` (the `TaskInfo` schema exposes both `number` and `pr_url`). Plan tasks (no `pr_url`) MUST be omitted from `prs`. This event is authoritative — do not rely on the SessionEnd hook.
    - Call `mcp__cloglog__unregister_agent` and **exit**. Do NOT call `get_my_tasks` or start the next task — the supervisor handles that.

**One task per session.** Each session ends after one PR merge (or after a plan+impl pair where the impl PR merges). Standalone no-PR tasks (docs, research, prototypes using `skip_pr=True`) also exit after completing — they run the same per-task shutdown sequence with `reason: "no_pr_task_complete"` instead of `"pr_merged"`, skipping `mark_pr_merged` and `pr_merged_notification`. Plan tasks are the only exception: they immediately start the following impl task in the same session. The supervisor sees `agent_unregistered`, checks for remaining backlog tasks on this worktree, and either relaunches with the continuation prompt (see **Continuation Prompt** below) or triggers close-wave if no tasks remain.

## Continuation Prompt

When the supervisor relaunches the same worktree for task N+1 after task N's PR merged and the agent exited, use this prompt instead of the initial launch prompt:

```
Read /abs/path/to/worktree/AGENT_PROMPT.md and all shutdown-artifacts/work-log-T-*.md files in that worktree, then begin the next task.
```

The initial AGENT_PROMPT.md is already in the worktree from the original launch — do not rewrite it. The prior work logs carry the context the new session needs. The new session bootstraps by reading the work logs (see the worktree-agent template's **Work-Log Bootstrap** step), then loads MCP tools, registers, starts the next backlog task, and proceeds normally.

**The launch SKILL writes the initial prompt; the supervisor writes continuation prompts.** Continuation sessions reuse `.cloglog/launch.sh` by passing the prompt as `$1` — this preserves the TERM/HUP signal trap and `_unregister_fallback` path from the initial launch. Do not invoke `claude` directly for relaunches; always go through `launch.sh` so crash/close-tab cleanup works identically for initial and continuation sessions.

## Supervisor Relaunch Flow

When the supervisor inbox receives `agent_unregistered` from a worktree agent:

1. Extract the `worktree_id` from the `agent_unregistered` event.
2. Call `mcp__cloglog__get_active_tasks` to get all non-done tasks in the project. Filter the result to tasks where `worktree_id == <unregistered worktree's uuid>` AND `status == "backlog"`. **Do NOT use `mcp__cloglog__get_my_tasks`** — that returns tasks scoped to the supervisor's own worktree registration, not the worktree that just unregistered.
3. **If backlog tasks remain** → relaunch in the same zellij tab:
   ```bash
   # Update task-model for the next task (T-332) — launch.sh reads this at
   # runtime, so writing it before relaunch gives the new session its correct model.
   # NEXT_TASK_MODEL comes from the backlog task's `model` field in get_active_tasks.
   printf '%s\n' "${NEXT_TASK_MODEL:-}" > "${WORKTREE_PATH}/.cloglog/task-model"

   # Go to the worktree's tab (same tab name as WORKTREE_NAME)
   zellij action go-to-tab-by-name "${WORKTREE_NAME}"
   # Issue the continuation prompt — the tab's current process has exited,
   # so the shell is at the prompt again
   zellij action write-chars "bash '${WORKTREE_PATH}/.cloglog/launch.sh' 'Read ${WORKTREE_PATH}/AGENT_PROMPT.md and all shutdown-artifacts/work-log-T-*.md files in ${WORKTREE_PATH}, then begin the next task.'"
   zellij action write "13"   # send Enter
   ```
4. **Confirmation phase applies to relaunches too.** A continuation prompt can trip the same bootstrap failures as an initial launch — `claude` can fail to start, the new task's `--model` can be unavailable, MCP can be down, the heredoc-rendered `launch.sh` can have decayed (T-353-class issue introduced by an unrelated edit). After issuing the relaunch keystrokes, watch `<project_root>/.cloglog/inbox` for an `agent_started` event whose `worktree` field equals `${WORKTREE_NAME}`, with the same `launch_confirm_timeout_seconds` deadline (default `90`) as Step 5. On timeout, emit the same diagnostic checklist (`query-tab-names` / `bash -n` / `agent-shutdown-debug.log` / `.env` / `head -3 launch.sh`) and hand off to the operator. **Do NOT silently retry the relaunch; do NOT loop up to N times.** The supervisor must NOT mark the worktree as continuing on the next task until either `agent_started` arrives or the operator has acted.
5. **If no backlog tasks remain** → invoke the `cloglog:close-wave` skill for this worktree.

## Pipeline (Features Only)
If this is a feature with spec/plan/impl tasks:
- Spec task: write design spec, create PR, wait for merge. On merge: `mark_pr_merged` → `report_artifact` → write per-task work log → `agent_unregistered` → exit. Supervisor relaunches for plan task.
- Plan task: write implementation plan (no PR needed), commit locally, then call `update_task_status(plan_task_id, "review", skip_pr=True)` and `report_artifact(plan_task_id, worktree_id, plan_path)`, then `start_task` on the impl task. **Known backend gap (T-NEW-b):** `start_task` on the impl returns 409 until the pipeline guard at `src/agent/services.py:237` accepts artifact-only predecessor resolution; a 409 is a runtime MCP tool error per §4.1, so when you hit it emit `mcp_tool_error` with `reason: "pipeline_guard_blocked"` to the main inbox and stop — main recognises that reason and handles the advance. See `${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md` §1 for context and §4.1 for the event shape.
- Impl task: implement the feature, create PR, wait for merge. On merge: write per-task work log → `agent_unregistered` → exit.
```

Use **absolute paths** when referencing the prompt file. Agents cannot reliably find files by relative path.

Do **not** inline shell variables in prompts. Write the prompt to a file, then reference it.

## Step 4: Create Worktrees and Launch Agents

For each task/feature, launch sequentially (not in parallel):

### 4a. Create the git worktree

```bash
WORKTREE_NAME="wt-<descriptive-name>"
WORKTREE_PATH="$(git rev-parse --show-toplevel)/.claude/worktrees/${WORKTREE_NAME}"
git fetch origin main
git worktree add -b "${WORKTREE_NAME}" "${WORKTREE_PATH}" origin/main
```

**IMPORTANT:** Always branch from `origin/main`, never `HEAD`. Local main may have unpushed commits that would leak into the worktree's PR diff as unrelated changes.

### 4b. Register agent on the board

Call `mcp__cloglog__register_agent` with the worktree name and path. This is done here (not deferred to the agent) so the board reflects the launch immediately.

### 4c. Run project-specific worktree setup

If the project has `.cloglog/on-worktree-create.sh`, run it. **Use absolute paths and pass `WORKTREE_PATH` as an env var — never `cd` into the new worktree.** The Bash tool's shell persists `cwd` between calls, so a `cd` into the new worktree leaks into every subsequent main-agent command and the main agent ends up looking like it's working inside the worktree it just spawned.

```bash
if [[ -x "${WORKTREE_PATH}/.cloglog/on-worktree-create.sh" ]]; then
  WORKTREE_PATH="${WORKTREE_PATH}" WORKTREE_NAME="${WORKTREE_NAME}" "${WORKTREE_PATH}/.cloglog/on-worktree-create.sh"
fi
```

### 4d. Write AGENT_PROMPT.md into the worktree

Copy the assembled prompt to `${WORKTREE_PATH}/AGENT_PROMPT.md`.

### 4e. Create zellij tab and launch agent

```bash
# Capture current tab's stable numeric ID before switching away
CURRENT_TAB_ID=$(zellij action current-tab-info 2>&1 | awk '/^id:/ {print $2}')

# Resolve the project root so the launcher can read backend_url and (as a
# fallback) the MCP API key. Falls back to the current repo.
PROJECT_ROOT="$(git rev-parse --show-toplevel)"

# Write task model for launch.sh — update before each relaunch with the next task's model
# TASK_MODEL comes from the task's `model` field resolved in Step 1b (may be empty)
printf '%s\n' "${TASK_MODEL:-}" > "${WORKTREE_PATH}/.cloglog/task-model"

# Write a launcher script — unquoted EOF expands ${WORKTREE_PATH} / ${PROJECT_ROOT}
# at write time, baking the absolute paths in. T-217: we do NOT use `exec claude`
# here. `exec` would replace the bash wrapper with claude, destroying any trap
# installed in this script — and a SIGTERM from close-wave (step 5) would then
# reach only claude, whose SessionEnd hook is best-effort under signal. By
# running claude as a subprocess and wait()ing for it, the TERM/HUP trap below
# fires reliably and we hit /agents/unregister-by-path directly before claude
# is killed. See ${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md §2 and the T-217 experiment
# output (tab-close sends no signal at all; only the kill step does).
cat > "${WORKTREE_PATH}/.cloglog/launch.sh" << EOF
#!/bin/bash
# Auto-generated by the cloglog launch skill. See plugins/cloglog/skills/launch/SKILL.md.
set -u

WORKTREE_PATH="${WORKTREE_PATH}"
PROJECT_ROOT="${PROJECT_ROOT}"

_backend_url() {
  # T-312: stdlib-only grep+sed scalar parse — same shape as the shared helper
  # at plugins/cloglog/hooks/lib/parse-yaml-scalar.sh. Inlined here because
  # launch.sh runs as a standalone bash exec inside the worktree, with no
  # CLAUDE_PLUGIN_ROOT in scope to source the helper from. Do NOT reintroduce
  # the python YAML lib here — the system python3 typically lacks PyYAML and
  # silently returns the default, breaking ports on portable hosts.
  local cfg="\$PROJECT_ROOT/.cloglog/config.yaml"
  local default="http://localhost:8000"
  [[ -f "\$cfg" ]] || { echo "\$default"; return; }
  local parsed
  parsed=\$(grep '^backend_url:' "\$cfg" 2>/dev/null | head -n1 \\
           | sed 's/^backend_url:[[:space:]]*//' \\
           | sed 's/[[:space:]]*#.*\$//' \\
           | tr -d '"' | tr -d "'")
  if [[ -n "\$parsed" ]]; then echo "\$parsed"; else echo "\$default"; fi
}

_read_scalar_yaml() {
  # T-348: read a top-level scalar key from a YAML file via grep+sed.
  # Same shape as _backend_url and parse-yaml-scalar.sh; do NOT reintroduce
  # the python YAML lib here (docs/invariants.md:76 — system python3
  # typically lacks PyYAML and silently returns the default).
  local file="\$1"; local key="\$2"
  [[ -f "\$file" ]] || return 0
  grep "^\${key}:" "\$file" 2>/dev/null | head -n1 \\
    | sed "s/^\${key}:[[:space:]]*//" \\
    | sed 's/[[:space:]]*#.*\$//' \\
    | tr -d '"' | tr -d "'"
}

_gh_app_id() {
  # Resolution order (T-348): env → .cloglog/local.yaml (gitignored,
  # host-local — preferred) → .cloglog/config.yaml (tracked fallback for
  # single-operator repos). Mirrors gh-app-token.py's _resolve precedence
  # exactly so an operator who keeps a temporary env override is honored,
  # not clobbered by stale YAML.
  [[ -n "\${GH_APP_ID:-}" ]] && { echo "\$GH_APP_ID"; return; }
  local v
  v=\$(_read_scalar_yaml "\$PROJECT_ROOT/.cloglog/local.yaml" "gh_app_id")
  [[ -n "\$v" ]] && { echo "\$v"; return; }
  _read_scalar_yaml "\$PROJECT_ROOT/.cloglog/config.yaml" "gh_app_id"
}

_gh_app_installation_id() {
  # See _gh_app_id resolution order above (env first).
  [[ -n "\${GH_APP_INSTALLATION_ID:-}" ]] && { echo "\$GH_APP_INSTALLATION_ID"; return; }
  local v
  v=\$(_read_scalar_yaml "\$PROJECT_ROOT/.cloglog/local.yaml" "gh_app_installation_id")
  [[ -n "\$v" ]] && { echo "\$v"; return; }
  _read_scalar_yaml "\$PROJECT_ROOT/.cloglog/config.yaml" "gh_app_installation_id"
}

_api_key() {
  # Authoritative lookup order matches mcp-server/src/credentials.ts and the
  # T-214 contract in ${CLAUDE_PLUGIN_ROOT}/docs/setup-credentials.md: env first, then
  # ~/.cloglog/credentials (mode 0600). The worktree's .env and the repo's
  # .mcp.json MUST NOT carry the key — tests/test_mcp_json_no_secret.py
  # pins that invariant and .cloglog/on-worktree-create.sh never writes
  # the key to .env.
  [[ -n "\${CLOGLOG_API_KEY:-}" ]] && { echo "\$CLOGLOG_API_KEY"; return; }
  local cred="\${HOME}/.cloglog/credentials"
  if [[ -r "\$cred" ]]; then
    local v
    v=\$(grep '^CLOGLOG_API_KEY=' "\$cred" 2>/dev/null | head -n 1 | cut -d= -f2-)
    # Strip optional surrounding single/double quotes to match
    # credentials.ts loadApiKey behaviour.
    v=\${v%\"}; v=\${v#\"}; v=\${v%\\'}; v=\${v#\\'}
    [[ -n "\$v" ]] && { echo "\$v"; return; }
  fi
  return 0
}

_unregister_fallback() {
  local sig="\${1:-unknown}"
  local url="\$(_backend_url)"
  local key="\$(_api_key)"
  echo "[\$(date -Iseconds)] launch.sh trap fired sig=\$sig worktree=\$WORKTREE_PATH" >> /tmp/agent-shutdown-debug.log
  if [[ -z "\$key" ]]; then
    echo "[\$(date -Iseconds)] launch.sh trap: no API key; skipping unregister POST" >> /tmp/agent-shutdown-debug.log
    return
  fi
  curl -s --max-time 5 -X POST "\${url}/api/v1/agents/unregister-by-path" \\
    -H "Content-Type: application/json" \\
    -H "Authorization: Bearer \${key}" \\
    -d "{\"worktree_path\": \"\${WORKTREE_PATH}\"}" \\
    >> /tmp/agent-shutdown-debug.log 2>&1 || true
}

CLEANUP_DONE=0
_on_signal() {
  local sig="\$1"
  [[ "\$CLEANUP_DONE" == "1" ]] && return
  CLEANUP_DONE=1
  _unregister_fallback "\$sig"
  if [[ -n "\${CLAUDE_PID:-}" ]] && kill -0 "\$CLAUDE_PID" 2>/dev/null; then
    kill -"\$sig" "\$CLAUDE_PID" 2>/dev/null || true
    # Give claude up to 5s to run its own SessionEnd hook before exiting.
    for _ in 1 2 3 4 5; do
      kill -0 "\$CLAUDE_PID" 2>/dev/null || break
      sleep 1
    done
  fi
  exit 0
}
trap '_on_signal TERM' TERM
trap '_on_signal HUP' HUP
trap '_on_signal INT' INT

cd "\$WORKTREE_PATH"
# T-348: export GitHub App identifiers so the github-bot skill's
# gh-app-token.py can mint installation tokens. These survive \`/clear\`
# because launch.sh re-exports them on every (re)launch, instead of
# relying on shell RC inheritance from whatever spawned zellij.
_GH_APP_ID="\$(_gh_app_id)"
_GH_APP_INSTALLATION_ID="\$(_gh_app_installation_id)"
[[ -n "\$_GH_APP_ID" ]] && export GH_APP_ID="\$_GH_APP_ID"
[[ -n "\$_GH_APP_INSTALLATION_ID" ]] && export GH_APP_INSTALLATION_ID="\$_GH_APP_INSTALLATION_ID"
# Read per-task model from .cloglog/task-model — written by the launch skill (T-332).
# The supervisor rewrites this file before each continuation relaunch so the
# correct model is used for every task, not just the initial one.
_MODEL_FLAG=""
_TASK_MODEL=\$(cat "\$WORKTREE_PATH/.cloglog/task-model" 2>/dev/null || true)
[[ -n "\$_TASK_MODEL" ]] && _MODEL_FLAG="--model \$_TASK_MODEL"
# Optional \$1: continuation prompt string from supervisor relaunch.
# When absent, fall back to reading AGENT_PROMPT.md (initial launch).
_CLAUDE_PROMPT="\${1:-Read ${WORKTREE_PATH}/AGENT_PROMPT.md and begin.}"
claude --dangerously-skip-permissions \${_MODEL_FLAG:+\$_MODEL_FLAG} "\$_CLAUDE_PROMPT" &
CLAUDE_PID=\$!
wait "\$CLAUDE_PID"
EOF
chmod +x "${WORKTREE_PATH}/.cloglog/launch.sh"

# new-tab -- <command> starts the command in the tab's initial pane — no write-chars, no list-clients, no pane-id needed
zellij action new-tab --name "${WORKTREE_NAME}" -- bash "${WORKTREE_PATH}/.cloglog/launch.sh"

# Return focus immediately using stable numeric ID (not affected by tab renames or reordering)
zellij action go-to-tab-by-id "${CURRENT_TAB_ID}"
```

> **`launch.sh` is operator-host-specific.** The unquoted heredoc above expands
> `${WORKTREE_PATH}` and `${PROJECT_ROOT}` at *write time*, baking absolute
> paths that are valid only on the current operator's machine into the script.
> The file is gitignored (`.gitignore`) so it is not a tracked source leak —
> but gitignored does **not** mean "safe to copy". Copying `launch.sh` between
> operators or hosts will produce a script that references non-existent paths on
> the target machine. Each host regenerates this file at launch time from its
> own current `WORKTREE_PATH`. Do not commit it, archive it, or hand it to
> another operator as a working artifact.

### 4f. One agent at a time

Wait briefly between each agent launch. Each needs its own zellij tab.

## Step 5: Verification

After all agents are launched, the main agent does NOT trust tab creation as proof of life. A spawned zellij tab can hold a crashed `claude`, a `bash` syntax error in `launch.sh` (e.g. T-353's antisocial heredoc bug — `unexpected EOF while looking for matching '"'`), a half-applied `on-worktree-create.sh`, or an MCP-unavailable abort, and `query-tab-names` will still list the tab. The only authoritative liveness signal is an `agent_started` event on `<project_root>/.cloglog/inbox` carrying the worktree's `worktree` field. Step 5 enforces a deadline on that event per launched worktree.

1. **List tabs** to confirm all were created:
   ```bash
   zellij action query-tab-names
   ```

2. **Confirmation phase — `agent_started` deadline.** For each launched worktree, watch `<project_root>/.cloglog/inbox` for an `agent_started` event whose `worktree` field equals the worktree name (e.g. `wt-t356-launch-confirm-timeout`). The deadline is `launch_confirm_timeout_seconds` from `.cloglog/config.yaml` (default `90` if the key is missing or malformed — read via the `parse-yaml-scalar.sh` shape, do NOT introduce a YAML library). The main agent already runs a persistent inbox Monitor — reuse it; do not spawn a second tail. Read the existing event stream with a deadline (e.g. an `until`-loop over `tail -F` filtered to `agent_started` lines for this `worktree`, bounded by `date +%s` against `start + launch_confirm_timeout_seconds`).

   - **Confirmed within deadline** → row in the summary table is marked `live` and carries the `worktree_id` from the event payload.
   - **Deadline elapsed with no matching event** → row is marked `LAUNCH FAILED — no agent_started in <N>s`. The main agent emits the diagnostic checklist below and **hands off to the operator**. The main agent does NOT silently retry; do NOT loop on the launch up to N times; every class of bootstrap failure has a different fix and the operator owns the call.

3. **Diagnostic checklist on timeout.** Print these commands verbatim for the operator (substitute `<worktree>` with the absolute worktree path and `<wt-name>` with the tab/branch name):

   1. `zellij action query-tab-names | grep <wt-name>` — tab present? Absent ⇒ launcher never ran.
   2. `bash -n <worktree>/.cloglog/launch.sh` — syntax valid? Non-zero ⇒ heredoc-rendering failure (T-353 class).
   3. `tail -20 /tmp/agent-shutdown-debug.log` — any trap fire mentioning this worktree? Process started then died on signal.
   4. `cat <worktree>/.env | grep -E 'CLOGLOG_API_KEY|DATABASE_URL'` — both set? Half-applied `on-worktree-create.sh`.
   5. `head -3 <worktree>/.cloglog/launch.sh` — first line is `#!/bin/bash`? Sanity check the file rendered at all.

   The main agent must NOT proceed to the "wait for review/merge" loop until either the `agent_started` event arrives (late-confirmation is fine — log it and continue) OR the operator has explicitly acted (relaunch, abort, or fix-and-retry instruction in the inbox). Treat the launch as failed in the summary table until then.

4. **Present a summary table** to the user showing:

   | Tab Name | Task/Feature | Title | Priority | Status |
   |----------|-------------|-------|----------|--------|
   | wt-... | T-45 | Fix bug in... | high | live (worktree_id `…`) |
   | wt-... | F-12 | Add search... | medium | LAUNCH FAILED — no agent_started in 90s |

## Rules

- **Never skip the git status check.** This is the #1 cause of agent confusion.
- **Always use absolute paths** for AGENT_PROMPT.md references.
- **Tab names must use `wt-*` pattern** for cleanup scripts and reconciliation to work.
- **Only close tabs you created** — never close tabs that were there before.
- **Sequential launch only** — worktrees share git state and must be created one at a time.
- **Board update is mandatory** — every launched agent must have its task tracked on the board.
