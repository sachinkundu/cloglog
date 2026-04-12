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

## Workflow
1. Read the project CLAUDE.md for project-specific instructions
2. Register: call `mcp__cloglog__register_agent` with this worktree path
3. Start task: call `mcp__cloglog__start_task` with the task ID
4. Run existing tests first to establish a green baseline
5. Implement the feature or fix
6. Run the project quality gate
7. Create PR using the github-bot skill
8. Move task to review with PR URL via `mcp__cloglog__update_task_status`
9. Poll for comments and merge using the github-bot skill
10. After merge: call `mcp__cloglog__get_my_tasks` — if more tasks remain, start the next one
11. When all tasks complete: call `mcp__cloglog__unregister_agent` and exit

## Pipeline (Features Only)
If this is a feature with spec/plan/impl tasks:
- Spec task: write design spec, create PR, wait for merge
- Plan task: write implementation plan (no PR needed), commit and proceed
- Impl task: implement the feature, create PR, wait for merge
- After each PR merges, call `mcp__cloglog__get_my_tasks` to get the next task
```

Use **absolute paths** when referencing the prompt file. Agents cannot reliably find files by relative path.

Do **not** inline shell variables in prompts. Write the prompt to a file, then reference it.

## Step 4: Launch Agents

For each task/feature, launch sequentially (not in parallel):

1. **Create a zellij tab** named after the worktree:
   ```bash
   zellij action new-tab --name wt-<descriptive-name>
   ```

2. **Launch claude with worktree isolation** in the zellij tab:
   ```bash
   zellij action write-chars "claude --dangerously-skip-permissions 'Read /absolute/path/to/AGENT_PROMPT.md and begin.'"
   sleep 0.3
   zellij action write 13
   ```

   The agent runs in its own worktree via Claude Code's native isolation.

3. **One agent at a time** with a brief pause between each. Each needs its own tab to be active.

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
