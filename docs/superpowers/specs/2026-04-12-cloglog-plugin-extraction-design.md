# Cloglog Plugin Extraction Design

**Date:** 2026-04-12
**Status:** Draft

## Problem

The cloglog project has developed a workflow discipline for managing multi-agent development: planning pipelines, worktree isolation, PR discipline, board-driven task tracking, and agent lifecycle management. This workflow is generic — it's not tied to cloglog's tech stack or architecture. But it's currently hardcoded into cloglog's `.claude/` directory, scripts, and CLAUDE.md.

We want to bring other projects (e.g. `~/code/exa-reports`) under cloglog management. Each project should get the same workflow discipline without reimplementing it. The solution is to extract the generic workflow into a Claude Code plugin that any project can install.

## Architecture

### Single Backend, Multi-Project

```
+---------------------------------------------+
|           cloglog backend (one)              |
|  PostgreSQL (one DB, project_id scoped)      |
|  SSE, API, MCP server                        |
+------+------------------+-------------------+
       |                  |
  cloglog repo       exa-reports repo
  (plugin consumer)  (plugin consumer)
       |                  |
  plugins/cloglog/   (installed via claude plugins install)
```

One cloglog backend instance. One database. Everything scoped by project. The MCP server serves all projects. The plugin is the client-side component that teaches agents how to work within the workflow.

### What the Plugin Is

- Agent orchestration discipline (register, pipeline, shutdown, artifact handoff)
- Board-driven workflow (backlog -> planning -> execution -> review)
- Worktree lifecycle management via Claude Code native worktrees
- The planning pipeline (spec -> plan -> impl) as a universal pattern
- PR discipline (bot identity, quality gate, demos, test reports)
- Zellij tab management for agent visibility
- Agent communication (inbox files, Monitor)

### What the Plugin Is NOT

- CLAUDE.md generation (standard tooling does this)
- Tech-stack-specific anything (no "run pytest" or "run vitest")
- Any particular architecture methodology (DDD, hexagonal, etc.)
- Quality gate implementation (each project defines its own)
- Infrastructure setup (ports, DBs, deps — project provides these)

## Plugin Structure

```
plugins/cloglog/
├── package.json              # Plugin metadata
├── README.md
├── skills/
│   ├── init/SKILL.md         # /cloglog init — onboard a project
│   ├── launch/SKILL.md       # /cloglog launch — create worktrees, launch agents
│   ├── close-wave/SKILL.md   # /cloglog close-wave — post-merge cleanup
│   ├── reconcile/SKILL.md    # /reconcile — detect/fix drift
│   └── github-bot/SKILL.md   # GitHub bot identity for all operations
├── agents/
│   ├── worktree-agent.md     # Generic pipeline runner (spec -> plan -> impl)
│   └── pr-postprocessor.md   # Post-merge cleanup, learnings extraction
├── hooks/
│   ├── worktree-create.sh    # WorktreeCreate — register agent on board
│   ├── worktree-remove.sh    # WorktreeRemove — run project cleanup, close zellij tab
│   ├── quality-gate.sh       # PreToolUse:Bash — run project's quality command
│   ├── agent-shutdown.sh     # SessionEnd — generate artifacts, unregister
│   ├── prefer-mcp.sh         # PreToolUse:Bash — block direct API calls
│   ├── remind-pr-update.sh   # PostToolUse:Bash — remind to update board after PR
│   ├── protect-worktree-writes.sh  # PreToolUse:Edit|Write — enforce scopes if defined
│   ├── enforce-task-transitions.sh # PreToolUse:mcp__cloglog__* — validate state machine
│   └── block-sensitive-files.sh    # PreToolUse:Edit|Write — block .env, credentials
├── settings.json             # Hook registrations
└── templates/
    ├── on-worktree-create.sh # Template for project-specific setup
    └── claude-md-fragment.md # Workflow rules to inject into project CLAUDE.md
```

## Skills

### `/cloglog init`

Onboards a new project. Run once per repo.

1. Ask project name (default: directory name)
2. Ask quality gate command (detect from Makefile/package.json if possible)
3. Register project on the cloglog board via MCP
4. Add cloglog MCP server to project's `.claude/settings.json`
5. Detect tech stack and generate `.cloglog/` directory:
   ```
   .cloglog/
   ├── config.yaml               # project name, backend URL, quality command
   ├── on-worktree-create.sh     # generated from detected stack (optional)
   └── on-worktree-destroy.sh    # cleanup counterpart (optional)
   ```
6. Inject workflow rules fragment into project's CLAUDE.md
7. Commit changes

Tech stack detection examples:
- `pyproject.toml` with uv -> `uv sync` in worktree setup
- `package.json` -> `npm install` in worktree setup
- Both (monorepo) -> handles both
- Neither -> empty or no setup script

The skill is idempotent — running again updates config without duplicating.

**`config.yaml` format:**
```yaml
project: exa-reports
backend_url: http://localhost:8000
quality_command: make check
worktree_scopes:           # optional
  # auth: [src/auth/, tests/auth/]
  # billing: [src/billing/, tests/billing/]
```

### `/cloglog launch`

Creates worktree agents for features or tasks.

```
/cloglog launch F-12          # launch agent for feature F-12
/cloglog launch T-45 T-46     # launch agents for standalone tasks
```

Steps:
1. Fetch feature/task details from board via MCP
2. For features: create all three pipeline tasks (spec, plan, impl) if they don't exist
3. Assemble agent prompt — feature context, assigned tasks, workflow rules, project config
4. Call Agent tool with `isolation: "worktree"` and the assembled prompt
5. Create zellij tab named after the worktree
6. Launch the agent in that tab
7. One agent at a time, sequentially

### `/cloglog close-wave`

Post-merge cleanup for completed worktrees.

```
/cloglog close-wave                    # auto-detect active worktrees
/cloglog close-wave wt-f12 wt-f13     # specific worktrees
```

Steps:
1. Verify all PRs are merged via `gh`
2. Generate work log (commits, files changed per worktree)
3. Close zellij tabs
4. Remove git worktrees
5. Clean remote branches
6. Update main branch
7. Run project's quality gate on main
8. Spawn pr-postprocessor agent to extract learnings

### `/reconcile`

Drift detection and auto-fix. Same as today but project-aware.

Checks:
- Board tasks vs actual PR state (merged but task not updated)
- Registered agents vs running sessions (stale registrations)
- Worktree branches vs remote branches (orphaned branches)
- Stale zellij tabs (tabs for removed worktrees)

Always auto-fixes — no separate "fix" step.

### `/github-bot`

Single GitHub App bot identity shared across all projects. Every `git push`, `gh pr create`, `gh api` call goes through the bot token. The skill provides the exact commands for:
- Pushing code
- Creating PRs
- Checking PR status and comments
- Replying to review comments
- CI failure recovery

Token acquisition is configurable (PEM path, app ID, installation ID) but defaults to the shared bot.

## Agents

### `worktree-agent` (Generic Pipeline Runner)

The workflow skeleton. Knows the planning pipeline, PR discipline, and agent lifecycle. Does NOT know any project's tech stack or architecture.

**Lifecycle:**
1. Start: call `get_my_tasks` to see assigned work
2. Follow pipeline order (enforced by backend guards):
   - **Spec task:** Write design spec, create PR, move to review, wait for merge, report artifact
   - **Plan task:** Write implementation plan, commit locally, proceed immediately (no PR)
   - **Impl task:** Implement using subagent-driven development, write tests, create PR, move to review, wait for merge
3. Between tasks: call `get_my_tasks` — more tasks -> continue; empty -> shutdown
4. Shutdown: generate artifacts (work-log.md, learnings.md), call unregister_agent

**How project-specific behavior works:** The agent reads the project's CLAUDE.md. If cloglog's CLAUDE.md says "spawn ddd-architect for specs and run contract-check", the agent does that. If exa-reports' CLAUDE.md says nothing special, the agent writes specs directly. The plugin provides the skeleton; the project's CLAUDE.md fills in the methodology.

**What's generic (in the plugin):**
- Pipeline discipline (spec -> plan -> impl ordering)
- PR workflow (bot identity, quality gate, test report, demo)
- Subagent-driven development for impl tasks
- Polling for PR comments and merge state
- Shutdown artifact generation
- Agent communication via inbox files

**What's project-specific (in project's CLAUDE.md and .claude/):**
- Which subagents to spawn at which phases
- Architecture methodology
- Tech-stack-specific commands
- Quality gate internals

### `pr-postprocessor` (Post-Merge Cleanup)

Spawned by `close-wave` after worktree PRs merge.

1. Read the PR diff
2. Extract learnings relevant to future development
3. Update the project's CLAUDE.md agent learnings section
4. Consolidate work logs

## Hooks

All hooks are registered in the plugin's `settings.json`.

| Hook | Event | Matcher | Behavior |
|------|-------|---------|----------|
| `worktree-create.sh` | WorktreeCreate | — | Register agent on board via MCP. Run `.cloglog/on-worktree-create.sh` if exists. |
| `worktree-remove.sh` | WorktreeRemove | — | Run `.cloglog/on-worktree-destroy.sh` if exists. Close zellij tab. |
| `quality-gate.sh` | PreToolUse | Bash | On `git commit`/`push`/`gh pr create`: read quality command from `.cloglog/config.yaml`, run it, block on failure. |
| `agent-shutdown.sh` | SessionEnd | — | If in worktree: generate work-log.md + learnings.md in `shutdown-artifacts/`, call unregister_agent. |
| `prefer-mcp.sh` | PreToolUse | Bash | Block curl/wget to cloglog backend URL (from config.yaml). Agents must use MCP tools. |
| `remind-pr-update.sh` | PostToolUse | Bash | After `gh pr create`, remind to call update_task_status with PR URL. |
| `protect-worktree-writes.sh` | PreToolUse | Edit\|Write | If `worktree_scopes` defined in config.yaml, enforce directory restrictions. No scopes = no-op. |
| `enforce-task-transitions.sh` | PreToolUse | mcp__cloglog__* | Validate state machine rules client-side (belt-and-suspenders with server guards). |
| `block-sensitive-files.sh` | PreToolUse | Edit\|Write | Block edits to .env, .mcp.json, credentials, secrets. |

## Worktree Lifecycle

### Creation

```
User: /cloglog launch F-12

1. launch skill assembles agent prompt with feature context + workflow rules
2. launch skill calls Agent(isolation: "worktree", prompt: ...)
3. Claude Code creates git worktree (native)
4. WorktreeCreate hook fires:
   a. Read .cloglog/config.yaml for project name + backend URL
   b. Call register_agent on board via MCP
   c. Run .cloglog/on-worktree-create.sh if exists (project's deps/ports/DB setup)
5. launch skill creates zellij tab, launches agent in it
6. Agent starts, calls get_my_tasks, begins pipeline
```

### Normal Completion

```
1. Agent completes all pipeline tasks
2. Agent generates shutdown artifacts (work-log.md, learnings.md)
3. Agent calls unregister_agent with artifact paths
4. Agent session exits
5. Worktree stays on disk until explicit cleanup
```

### Cleanup (User-Initiated)

```
User: /cloglog close-wave

1. Verify all PRs merged
2. Generate work log
3. Close zellij tabs for each worktree
4. Remove git worktrees (triggers WorktreeRemove hook)
5. WorktreeRemove hook runs .cloglog/on-worktree-destroy.sh if exists
6. Clean remote branches
7. Run quality gate on main
8. Spawn pr-postprocessor for learnings
```

### Unexpected Termination (SIGTERM)

```
1. SessionEnd hook fires
2. Hook generates shutdown artifacts
3. Hook calls unregister_agent (best-effort)
4. Worktree stays on disk until explicit cleanup
```

## State Machine Guards

All workflow discipline is enforced server-side in the cloglog backend (`src/agent/services.py`). The plugin does not replicate these — agents hit the API and the API enforces the rules.

Guards:
- **Pipeline ordering:** spec must complete before plan, plan before impl
- **Artifact gates:** spec/plan tasks must have `report_artifact` before downstream can start
- **State transitions:** agents cannot mark tasks "done" (only dashboard), PR URL required for "review"
- **One-active-task:** agent cannot start a second task while one is in-progress/review (unless PR merged)
- **PR URL uniqueness:** no reuse within a feature

The `enforce-task-transitions.sh` hook is belt-and-suspenders — it catches obvious violations client-side before they hit the API.

## Project Contract

What a project must provide to use the plugin:

**Required:**
- A git repo
- A quality gate command (anything that returns 0/1)

**Optional:**
- `.cloglog/on-worktree-create.sh` — project-specific worktree setup (deps, ports, DB)
- `.cloglog/on-worktree-destroy.sh` — project-specific worktree cleanup
- `worktree_scopes` in config.yaml — directory restrictions per worktree
- Project-specific agents in `.claude/agents/` (referenced from CLAUDE.md)
- Project-specific skills in `.claude/skills/`

The `/cloglog init` skill generates the `.cloglog/` directory and detects reasonable defaults. A project with zero custom setup still gets the full workflow.

## Extraction Plan for Cloglog

Cloglog is the first consumer. The extraction must leave cloglog working identically.

### What Moves to the Plugin

| Current Location | Plugin Location | Notes |
|-----------------|----------------|-------|
| `.claude/commands/launch-worktree.md` | `skills/launch/SKILL.md` | Generalize, remove DDD references |
| `.claude/commands/close-wave.md` | `skills/close-wave/SKILL.md` | Generalize |
| `.claude/skills/reconcile/` | `skills/reconcile/SKILL.md` | Make project-aware |
| `.claude/skills/github-bot/` | `skills/github-bot/SKILL.md` | Already generic |
| `.claude/agents/worktree-agent.md` | `agents/worktree-agent.md` | Strip cloglog-specific, keep skeleton |
| `.claude/agents/pr-postprocessor.md` | `agents/pr-postprocessor.md` | Strip cloglog-specific |
| `.claude/hooks/quality-gate-before-commit.sh` | `hooks/quality-gate.sh` | Read command from config.yaml |
| `.claude/hooks/agent-shutdown.sh` | `hooks/agent-shutdown.sh` | Already generic |
| `.claude/hooks/prefer-mcp-over-api.sh` | `hooks/prefer-mcp.sh` | Read backend URL from config.yaml |
| `.claude/hooks/remind-pr-board-update.sh` | `hooks/remind-pr-update.sh` | Already generic |
| `.claude/hooks/protect-worktree-writes.sh` | `hooks/protect-worktree-writes.sh` | Read scopes from config.yaml |
| `.claude/hooks/enforce-task-transitions.sh` | `hooks/enforce-task-transitions.sh` | Already generic |
| `.claude/hooks/block-sensitive-files.sh` | `hooks/block-sensitive-files.sh` | Already generic |
| CLAUDE.md agent learnings section | `templates/claude-md-fragment.md` | Generic workflow rules only |

### What Stays in Cloglog

| Location | Why |
|----------|-----|
| `.claude/agents/ddd-architect.md` | DDD methodology |
| `.claude/agents/ddd-reviewer.md` | DDD methodology |
| `.claude/agents/test-writer.md` | Cloglog-specific testing patterns |
| `.claude/agents/migration-validator.md` | Alembic-specific |
| `.claude/skills/db-migration/` | Alembic-specific |
| `scripts/worktree-infra.sh` | Becomes `.cloglog/on-worktree-create.sh` |
| `scripts/worktree-ports.sh` | Used by cloglog's worktree setup |
| `scripts/gh-app-token.py` | Bot token acquisition (referenced by plugin's github-bot skill) |
| CLAUDE.md project-specific sections | DDD, tech stack, bounded contexts |

### What Gets Deleted (Replaced by Plugin + Native Worktrees)

| Location | Replaced By |
|----------|-------------|
| `scripts/create-worktree.sh` | Claude Code native `isolation: "worktree"` + WorktreeCreate hook + `.cloglog/on-worktree-create.sh` |
| `scripts/manage-worktrees.sh` | `/cloglog close-wave` skill + WorktreeRemove hook |
| `scripts/list-worktrees.sh` | `/reconcile` skill |
| `.claude/hooks/log-agent-spawn.sh` | Dropped or made optional telemetry |

### New Files in Cloglog

| Location | Purpose |
|----------|---------|
| `.cloglog/config.yaml` | Project config (name, backend URL, quality command, worktree scopes) |
| `.cloglog/on-worktree-create.sh` | Extracted from create-worktree.sh — just the infra setup (ports, DB, deps) |
| `.cloglog/on-worktree-destroy.sh` | Extracted from manage-worktrees.sh — just the infra teardown |

### Migration Steps

1. Create `plugins/cloglog/` with full plugin structure
2. Extract and generalize each skill, agent, hook
3. Create `.cloglog/config.yaml` for cloglog
4. Extract infra setup from `create-worktree.sh` into `.cloglog/on-worktree-create.sh`
5. Extract infra teardown from `manage-worktrees.sh` into `.cloglog/on-worktree-destroy.sh`
6. Update cloglog's `.claude/settings.json` to use plugin hooks
7. Split CLAUDE.md: generic rules -> plugin template, project-specific stays
8. Remove replaced scripts
9. **Test: launch a worktree agent for a real feature, verify full pipeline**
10. **Test: close the wave, verify cleanup works**
11. **Test: reconcile, verify drift detection works**
12. **Test: quality gate blocks bad commits**
13. **Test: worktree scopes enforce directory restrictions**

## Success Criteria

- Cloglog works identically to before the extraction
- A new project can run `/cloglog init` and get the full workflow
- Worktree agents follow the planning pipeline without project-specific plugin changes
- All hooks fire correctly via Claude Code native worktree lifecycle
- State machine guards continue to enforce discipline server-side
