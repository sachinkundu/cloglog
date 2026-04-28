# cloglog

Multi-project Kanban dashboard for managing autonomous AI coding agents running in git worktrees.

## What it is

cloglog gives you board-driven workflow for AI agents. You create tasks on a Kanban board; agents pick them up, implement them in isolated git worktrees, create PRs, and hand off for review — with automated PR review via Codex CLI and optional OpenCode.

The **cloglog plugin** (`plugins/cloglog/`) is the operator-facing surface. It ships skills (`/cloglog init`, `/cloglog setup`, `/cloglog launch`, etc.), hooks (quality gate, worktree scope guard, session bootstrap), and agent prompt templates. The long-term goal is for the plugin to work with any project; cross-project portability is actively being hardened — see `docs/design/plugin-portability-audit.md` for current status.

## Prerequisites

Before onboarding a new project with `/cloglog init`, ensure the following are in place.

### 1. Plugin installed

The cloglog plugin must be installed in Claude Code. Currently the plugin is distributed as a local folder install:

```bash
claude plugins install /path/to/plugins/cloglog
```

Replace `/path/to/plugins/cloglog` with the absolute path to the `plugins/cloglog` directory in this repo (or wherever you have the plugin checked out). After install, restart Claude Code — the plugin is loaded at session start.

Confirm with `/help`: the cloglog skills (`/cloglog init`, `/cloglog setup`, etc.) should appear in the skill list.

### 2. Backend running

The cloglog backend must be accessible before you run `/cloglog init`. The default address is `http://127.0.0.1:8001`.

- **Dev backend** (this repo): `make dev` starts the dev backend on port 8000 (not 8001 — use `make prod` for 8001)
- **Prod backend**: `make prod` binds on port 8001 — this is the target `/cloglog init` connects to by default

Verify: `curl -sf http://127.0.0.1:8001/health | python3 -m json.tool`

### 3. `DASHBOARD_SECRET` exported

Step 2 of `/cloglog init` bootstraps a new project via a direct HTTP call authenticated with your `DASHBOARD_SECRET` (the same value in the backend's `.env`). Export it before starting init:

```bash
export DASHBOARD_SECRET=<value from your backend's .env>
```

Add this to `~/.bashrc` or `~/.zshenv` so every shell (and every Claude Code session) inherits it automatically.

### 4. GitHub App credentials (optional at init time)

Steps 6–7 of `/cloglog init` configure bot identity for agent PRs. You can skip this at init and complete it later, but agents won't be able to push or create PRs until it's done.

Required for bot operations:
- `~/.agent-vm/credentials/github-app.pem` — App private key
- `GH_APP_ID` and `GH_APP_INSTALLATION_ID` exported in your shell

See `docs/setup-credentials.md` for detailed bot setup instructions.

## Quick start — new project

Open Claude Code in the project directory and run:

```
/cloglog init
```

The skill walks you through:
1. Project name and quality gate detection
2. Backend registration (creates the project, writes `~/.cloglog/credentials`)
3. MCP server configuration in `.claude/settings.json`
4. `.cloglog/` directory setup (config, worktree hooks)
5. CLAUDE.md workflow rules injection
6. GitHub bot identity verification
7. Codex PR review setup

**Two-phase flow:** After Step 2 creates the project and writes credentials, the skill asks you to restart Claude Code. The MCP server reads credentials at startup. After restart, run `/cloglog init` again — the remaining steps complete automatically.

## Session start

Each time you open a project that's already initialized:

```
/cloglog setup
```

This registers the main agent with the board and starts the inbox monitor for the session.

## Launching agents

```
/cloglog launch T-42
```

Creates an isolated git worktree, launches a Claude Code agent in a Zellij pane, and assigns the task. The agent registers with the board, implements the task, creates a PR, and unregisters when done.

## Docs

- `docs/setup-credentials.md` — API key, GitHub bot credentials, credential resolution order
- `plugins/cloglog/skills/init/SKILL.md` — full init skill reference with all steps
- `docs/design/agent-lifecycle.md` — agent lifecycle protocol (registration, heartbeat, shutdown)
- `docs/ddd-context-map.md` — cloglog's own DDD bounded contexts (project-specific)
- `docs/design/plugin-portability-audit.md` — audit of cloglog-specific leaks in the plugin
