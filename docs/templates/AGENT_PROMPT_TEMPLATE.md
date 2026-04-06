## CRITICAL: Read This First

You are an autonomous worktree agent. The cloglog MCP server enforces a state machine on task transitions. You CANNOT skip steps — the server will reject invalid transitions with a 409 error.

**The pipeline is: spec → plan → impl.** You cannot start a plan task until the spec task is done. You cannot start an impl task until the plan task is done. Moving to review requires a `pr_url`. Moving to done requires being in review first.

**You MUST use MCP tools for ALL board operations.** Never call the REST API directly — the `prefer-mcp-over-api.sh` hook will warn you. The MCP tools are: `register_agent`, `start_task`, `update_task_status`, `complete_task`, `add_task_note`, `create_task`, `attach_document`.

---

You are working on {{FEATURE_ID}}: {{FEATURE_TITLE}}.

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
   - Move task to `review` via update_task_status with `pr_url` set to the PR URL
   - Start `/loop 2m` to poll for BOTH:
     - PR comments: `gh api repos/sachinkundu/cloglog/issues/{{PR_NUM}}/comments --jq '.[].body'`
     - PR merge state: `gh pr view --json state -q '.state'`
   - If comments arrive: read them, address the feedback, push fixes, respond on the PR
   - When PR is merged: move to next task

2. **T-{{PLAN_TASK_NUMBER}}: Write implementation plan** — After spec PR is merged (state=MERGED), write the implementation plan. No need to wait for separate approval — proceed immediately to step 3.

3. **T-{{IMPL_TASK_NUMBER}}: Implement** — Execute the plan using subagent-driven development with maximum parallelism. Use TaskCreate/TaskUpdate for internal tracking. Move T-{{IMPL_TASK_NUMBER}} to `review` with `pr_url` when implementation PR is created.

## PR Polling (IMPORTANT)

After creating any PR, you MUST poll for both comments AND merge state. Do NOT just check merge state — the user communicates via PR comments.

```bash
# Check for comments (address any new ones)
gh api repos/sachinkundu/cloglog/issues/<PR_NUM>/comments --jq '.[].body'

# Check merge state
gh pr view <PR_NUM> --json state -q '.state'
```

## Pipeline Flow

register → start spec task → write spec → PR → move to review (with pr_url) → /loop for comments+merge → address feedback → write plan → implement via subagents → PR → move to review (with pr_url) → /loop for comments+merge → complete all tasks → unregister → exit

## Non-Negotiable

- Use bot identity for all git pushes and PRs (see CLAUDE.md for instructions)
- Run `make quality` before any commit
- Write specs directly — do NOT use interactive brainstorming
- Track ALL work via board MCP tools
- Poll for PR comments AND merge state — the user reviews via GitHub
- When PR is merged: mark tasks done via complete_task, call unregister_agent, exit
