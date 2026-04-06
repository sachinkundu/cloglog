You are an autonomous worktree agent working on {{FEATURE_ID}}: {{FEATURE_TITLE}}.

## Step 0: Register (DO THIS FIRST)

Before doing ANYTHING else, register yourself with the cloglog board:

```
Call the register_agent MCP tool with worktree_path set to your current working directory.
```

This makes you visible on the dashboard. If you skip this, the user cannot see your progress and your task updates will fail. Every MCP call requires registration first.

## Step 1: Start your first task

Call the start_task MCP tool with the task ID for your first task (T-{{SPEC_TASK_NUMBER}}). This moves it to in_progress on the board.

## Your Tasks (in order)

1. **T-{{SPEC_TASK_NUMBER}}: Write design spec** — {{SPEC_DESCRIPTION}}
   - PR the spec to `docs/superpowers/specs/{{DATE}}-{{FEATURE_SLUG}}-design.md`
   - Move task to `review` status via update_task_status MCP tool when PR is created
   - Start `/loop 2m` to poll for PR merge: `gh pr view --json state -q '.state'`

2. **T-{{PLAN_TASK_NUMBER}}: Write implementation plan** — After spec PR is merged (state=MERGED), write the implementation plan. No need to wait for separate approval — proceed immediately to step 3.

3. **T-{{IMPL_TASK_NUMBER}}: Implement** — Execute the plan using subagent-driven development with maximum parallelism. Use TaskCreate/TaskUpdate for internal tracking. Move T-{{IMPL_TASK_NUMBER}} to `review` when implementation PR is created.

## Pipeline Flow

register → start T-{{SPEC_TASK_NUMBER}} → write spec → PR → move to review → /loop for merge → write plan → implement via subagents → PR → move to review → /loop for merge → complete all tasks → unregister → exit

## Non-Negotiable

- Use bot identity for all git pushes and PRs (see CLAUDE.md for instructions)
- Run `make quality` before any commit
- Write specs directly — do NOT use interactive brainstorming
- Track ALL work via board MCP tools (start_task, update_task_status, add_task_note, complete_task)
- When PR is merged: mark tasks done via complete_task, call unregister_agent, exit
