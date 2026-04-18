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
Monitor your inbox for messages from the main agent:
```
Monitor(
  command: "tail -f <WORKTREE_PATH>/.cloglog/inbox",
  description: "Messages from main agent",
  persistent: true
)
```
When you receive a message, read it and act on the instruction. The main agent may send rebasing requests, priority changes, or other guidance.

## Workflow
1. Read the project CLAUDE.md for project-specific instructions
2. Load MCP tools: call `ToolSearch(query: "select:mcp__cloglog__register_agent,mcp__cloglog__start_task,mcp__cloglog__update_task_status,mcp__cloglog__get_my_tasks,mcp__cloglog__unregister_agent,mcp__cloglog__add_task_note")` — MCP tools are deferred and MUST be loaded via ToolSearch before calling them. If ToolSearch returns no matches, MCP is unavailable — stop and notify the main agent.
3. Start inbox monitor (see Inbox section above)
4. Register: call `mcp__cloglog__register_agent` with this worktree path
5. Start task: call `mcp__cloglog__start_task` with the task ID
6. Run existing tests first to establish a green baseline
7. Implement the feature or fix
8. Run the project quality gate
9. Produce proof-of-work demo — invoke the demo skill (`cloglog:demo`) to
   capture the feature working and generate `docs/demos/<branch>/demo.md`
10. Create PR using the github-bot skill with the demo document at the top
11. Move task to review with PR URL via `mcp__cloglog__update_task_status`
12. Poll for comments and merge using the github-bot skill
13. After merge: call `mcp__cloglog__get_my_tasks` — if more tasks remain, start the next one
13. When all tasks complete: call `mcp__cloglog__unregister_agent` and exit

## Pipeline (Features Only)
If this is a feature with spec/plan/impl tasks:
- Spec task: write design spec, create PR, wait for merge
- Plan task: write implementation plan (no PR needed), commit and proceed
- Impl task: implement the feature, create PR, wait for merge
- After each PR merges, call `mcp__cloglog__get_my_tasks` to get the next task
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

If the project has `.cloglog/on-worktree-create.sh`, run it:
```bash
if [[ -x ".cloglog/on-worktree-create.sh" ]]; then
  WORKTREE_PATH="${WORKTREE_PATH}" WORKTREE_NAME="${WORKTREE_NAME}" .cloglog/on-worktree-create.sh
fi
```

### 4d. Write AGENT_PROMPT.md into the worktree

Copy the assembled prompt to `${WORKTREE_PATH}/AGENT_PROMPT.md`.

### 4e. Create zellij tab and launch agent (no-focus-steal pattern)

**IMPORTANT:** Do NOT use `--cwd` on `zellij action new-tab` — it does not reliably set the shell's working directory. Instead, use `cd` in the command itself. The agent's Claude Code session MUST start from the worktree directory so it picks up `.mcp.json` and resolves the correct project root.

```bash
# 1. Remember current tab
CURRENT_TAB=$(zellij action query-tab-names 2>&1 | head -1)

# 2. Create the tab (briefly steals focus)
zellij action new-tab --name "${WORKTREE_NAME}"

# 3. Grab the pane ID while on the new tab
sleep 0.5
PANE_ID=$(zellij action list-clients 2>&1 | awk 'NR==2{print $2}')

# 4. Switch back immediately
zellij action go-to-tab-name "${CURRENT_TAB}"

# 5. Send command remotely — cd first, then claude
sleep 0.3
zellij action write-chars --pane-id "${PANE_ID}" "cd ${WORKTREE_PATH} && claude --dangerously-skip-permissions 'Read ${WORKTREE_PATH}/AGENT_PROMPT.md and begin.'"
sleep 0.3
zellij action write --pane-id "${PANE_ID}" 13
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
