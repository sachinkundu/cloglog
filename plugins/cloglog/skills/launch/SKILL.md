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

Parse `$ARGUMENTS` to extract feature/task identifiers (F-*, T-*). Look up the actual UUIDs using MCP tools:
- `mcp__cloglog__get_board` to find tasks/features
- `mcp__cloglog__list_features` for feature details

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
2. Load MCP tools: call `ToolSearch(query: "select:mcp__cloglog__register_agent,mcp__cloglog__start_task,mcp__cloglog__update_task_status,mcp__cloglog__get_my_tasks,mcp__cloglog__unregister_agent,mcp__cloglog__add_task_note,mcp__cloglog__mark_pr_merged,mcp__cloglog__report_artifact")` — MCP tools are deferred and MUST be loaded via ToolSearch before calling them.

   **Stop on MCP failure.** Halt on any MCP failure: startup unavailability emits `mcp_unavailable` and exits; runtime tool errors emit `mcp_tool_error` and wait for the main agent; transient network errors get one backoff retry before escalating. See `docs/design/agent-lifecycle.md` §4.1 for both event shapes.
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
13. Your `.cloglog/inbox` Monitor delivers review/merge/CI events automatically — do NOT start a `/loop`. On `pr_merged`: call `mcp__cloglog__mark_pr_merged(task_id, worktree_id)`, then for `spec`/`plan` tasks call `mcp__cloglog__report_artifact(task_id, worktree_id, artifact_path)`, then `mcp__cloglog__get_my_tasks` and start the next `backlog` task. See the `github-bot` skill's PR Event Inbox section for each event's shape.
14. Exit condition — `get_my_tasks` returns no task in `backlog` status. Then run the shutdown sequence:
    - Generate `shutdown-artifacts/work-log.md` and `shutdown-artifacts/learnings.md` inside the worktree (use absolute paths when referring to them).
    - **Emit `agent_unregistered` to `<project_root>/.cloglog/inbox` before `unregister_agent`.** Shape:
      ```json
      {
        "type": "agent_unregistered",
        "worktree": "<wt-name>",
        "worktree_id": "<uuid>",
        "ts": "<utc-iso>",
        "tasks_completed": ["T-NNN"],
        "artifacts": {
          "work_log": "/abs/path/shutdown-artifacts/work-log.md",
          "learnings": "/abs/path/shutdown-artifacts/learnings.md"
        },
        "reason": "all_assigned_tasks_complete"
      }
      ```
      Absolute paths are required so the main agent can read the artifacts after the worktree is torn down. This event is authoritative — do not rely on the SessionEnd hook to emit it for you.
    - Call `mcp__cloglog__unregister_agent` and exit.

## Pipeline (Features Only)
If this is a feature with spec/plan/impl tasks:
- Spec task: write design spec, create PR, wait for merge. On merge: `mark_pr_merged` → `report_artifact` with spec path.
- Plan task: write implementation plan (no PR needed), commit locally, then call `update_task_status(plan_task_id, "review", skip_pr=True)` and `report_artifact(plan_task_id, worktree_id, plan_path)`, then `start_task` on the impl task. **Known backend gap (T-NEW-b):** `start_task` on the impl returns 409 until the pipeline guard at `src/agent/services.py:237` accepts artifact-only predecessor resolution; a 409 is a runtime MCP tool error per §4.1, so when you hit it emit `mcp_tool_error` with `reason: "pipeline_guard_blocked"` to the main inbox and stop — main recognises that reason and handles the advance. See `docs/design/agent-lifecycle.md` §1 for context and §4.1 for the event shape.
- Impl task: implement the feature, create PR, wait for merge.
- After each PR merges, call `mcp__cloglog__get_my_tasks` to get the next task.
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

# Write a launcher script — unquoted EOF expands ${WORKTREE_PATH} / ${PROJECT_ROOT}
# at write time, baking the absolute paths in. T-217: we do NOT use `exec claude`
# here. `exec` would replace the bash wrapper with claude, destroying any trap
# installed in this script — and a SIGTERM from close-wave (step 5) would then
# reach only claude, whose SessionEnd hook is best-effort under signal. By
# running claude as a subprocess and wait()ing for it, the TERM/HUP trap below
# fires reliably and we hit /agents/unregister-by-path directly before claude
# is killed. See docs/design/agent-lifecycle.md §2 and the T-217 experiment
# output (tab-close sends no signal at all; only the kill step does).
cat > "${WORKTREE_PATH}/.cloglog/launch.sh" << EOF
#!/bin/bash
# Auto-generated by the cloglog launch skill. See plugins/cloglog/skills/launch/SKILL.md.
set -u

WORKTREE_PATH="${WORKTREE_PATH}"
PROJECT_ROOT="${PROJECT_ROOT}"

_backend_url() {
  local cfg="\$PROJECT_ROOT/.cloglog/config.yaml"
  [[ -f "\$cfg" ]] || { echo "http://localhost:8000"; return; }
  python3 -c "
import yaml
print(yaml.safe_load(open('\$cfg')).get('backend_url','http://localhost:8000'))
" 2>/dev/null || echo "http://localhost:8000"
}

_api_key() {
  # Authoritative lookup order matches mcp-server/src/credentials.ts and the
  # T-214 contract in docs/setup-credentials.md: env first, then
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
claude --dangerously-skip-permissions 'Read '"\$WORKTREE_PATH"'/AGENT_PROMPT.md and begin.' &
CLAUDE_PID=\$!
wait "\$CLAUDE_PID"
EOF
chmod +x "${WORKTREE_PATH}/.cloglog/launch.sh"

# new-tab -- <command> starts the command in the tab's initial pane — no write-chars, no list-clients, no pane-id needed
zellij action new-tab --name "${WORKTREE_NAME}" -- bash "${WORKTREE_PATH}/.cloglog/launch.sh"

# Return focus immediately using stable numeric ID (not affected by tab renames or reordering)
zellij action go-to-tab-by-id "${CURRENT_TAB_ID}"
```

### 4f. One agent at a time

Wait briefly between each agent launch. Each needs its own zellij tab.

## Step 5: Verification

After all agents are launched:

1. **List tabs** to confirm all were created:
   ```bash
   zellij action query-tab-names
   ```

2. **Present a summary table** to the user showing:

   | Tab Name | Task/Feature | Title | Priority | Status |
   |----------|-------------|-------|----------|--------|
   | wt-... | T-45 | Fix bug in... | high | launched |
   | wt-... | F-12 | Add search... | medium | launched |

## Rules

- **Never skip the git status check.** This is the #1 cause of agent confusion.
- **Always use absolute paths** for AGENT_PROMPT.md references.
- **Tab names must use `wt-*` pattern** for cleanup scripts and reconciliation to work.
- **Only close tabs you created** — never close tabs that were there before.
- **Sequential launch only** — worktrees share git state and must be created one at a time.
- **Board update is mandatory** — every launched agent must have its task tracked on the board.
