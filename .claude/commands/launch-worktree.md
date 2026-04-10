Launch worktree agents for one or more tasks. Handles the full lifecycle: clean state, create worktrees, set up infra, write prompts, launch in zellij, and verify.

The user may specify tasks by number (T-138), by feature (F-13), or describe what they want. Resolve entity numbers using MCP search or board tools.

## Pre-flight checks

Before creating ANY worktree:

1. **Check for uncommitted changes.** Run `git status`. If there are uncommitted changes, STOP and commit them first. Worktrees branch from HEAD and inherit dirty state — agents will see those diffs and think it's their work. This is non-negotiable.

2. **Resolve task IDs.** If the user said "F-13" or "T-138", look up the actual UUIDs. Use `get_board`, `list_features`, or `list_epics` MCP tools. If a search MCP tool exists, use that.

3. **Check task status.** Only launch agents for tasks in `backlog` status. Skip tasks that are already `in_progress`, `review`, or `done`.

4. **Plan worktree names.** Name worktrees descriptively based on the task: `wt-ui-dnd`, `wt-ui-search`, etc. Don't use generic names like `wt-1`, `wt-2`.

5. **Assess conflict risk.** If multiple tasks touch the same files (e.g., all frontend tasks), warn the user about merge conflict risk but proceed if they confirm.

## Creating worktrees

Create worktrees **sequentially** (not in parallel) since they share git state:

```bash
./scripts/create-worktree.sh <worktree-name>
```

**Check the exit code.** Exit code 0 means success. Any non-zero exit code means something failed — read the output and diagnose before proceeding. Common failures:
- Exit code 2 from psql: wrong database credentials (check `scripts/worktree-infra.sh` defaults match docker-compose.yml)
- Missing npm/uv: dependency not installed
- Alembic migration failure: check DATABASE_URL is using the right driver (`postgresql+asyncpg://`)

**Verify each worktree** has a `.env` file after creation:
```bash
cat /path/to/worktree/.env
```
If `.env` is missing, the infra setup failed. Don't proceed — fix the issue first.

## Writing agent prompts

Write an `AGENT_PROMPT.md` in each worktree directory. The prompt must include:

1. **Task title and description** — what to build/fix
2. **Task ID and Feature ID** — exact UUIDs so the agent can call MCP tools
3. **Context** — which directories to work in, how to run tests
4. **Workflow steps** — register, start_task, implement, create PR, move to review, poll

**Use absolute paths** when referencing the prompt file. Agents can't reliably find files by relative path.

**Don't inline shell variables** in prompts. Write the prompt to a file, then tell the agent to read it.

### Prompt template

```markdown
# Agent Prompt: <worktree-name>

## Task
**T-<number>: <title>**
Priority: <priority>

## What to Build/Fix
<description from the task>

## Context
- Frontend code in `frontend/`, backend in `src/<context>/`
- Run frontend tests: `cd frontend && npx vitest run`
- Run backend tests: `uv run pytest tests/<context>/ -x -q`
- Start your own backend: `source scripts/worktree-ports.sh && uv run uvicorn src.gateway.app:create_app --factory --port $BACKEND_PORT --reload`

## Task IDs
- Task ID: `<uuid>`
- Feature ID: `<uuid>`

## Workflow
1. Register: `register_agent` with this worktree path
2. Start task: `start_task` with the task ID
3. Run existing tests first to establish baseline
4. Implement with tests
5. Create PR, move task to review with PR URL
6. Poll for comments and merge
```

## Launching in zellij

For each worktree, create a zellij tab and launch claude:

```bash
# Create tab named after the worktree, with cwd set
zellij action new-tab --name <worktree-name> --cwd /path/to/worktree

# Type the claude command (use absolute path for the prompt)
zellij action write-chars "claude --dangerously-skip-permissions 'Read /absolute/path/to/worktree/AGENT_PROMPT.md and begin.'"

# Send Enter
sleep 0.3
zellij action write 13
```

Launch agents **one at a time** with a brief pause between each. Don't batch all the `write-chars` calls — each needs its own tab to be active.

## Verification

After all agents are launched:

1. **List tabs** to confirm all were created:
   ```bash
   zellij action list-tabs
   ```

2. **Present a summary table** to the user showing:
   - Tab name
   - Task number and title
   - Priority
   - Worktree path

## Rules

- **Never skip the git status check.** This is the #1 cause of agent confusion.
- **Never ignore script errors.** Exit code != 0 means something broke. Diagnose it.
- **Always verify .env exists** before launching an agent in a worktree.
- **Always use absolute paths** for AGENT_PROMPT.md references.
- **Each worktree runs its own infra** — own backend port, frontend port, and database. The generated CLAUDE.md tells agents how to start their servers.
- **Tab names must match worktree names** (`wt-*` pattern) for cleanup scripts to work.
- **Only close tabs you created** — never close tabs that were there before.
