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

Step 6 of `/cloglog init` configures bot identity for agent PRs. You can skip this at init and complete it later, but agents won't be able to push or create PRs until it's done.

Required for bot operations (all three are **host-local** — they don't travel with the repo and must be present on every machine):

- `~/.agent-vm/credentials/github-app.pem` — App private key
- `GH_APP_ID` and `GH_APP_INSTALLATION_ID` **exported** in your shell. A repo-local `.env` file is *not* sourced by Claude Code or the bot-token script — add the `export …` lines to `~/.bashrc` / `~/.zshenv` or use direnv. Verify with `printenv GH_APP_ID GH_APP_INSTALLATION_ID` in a fresh shell.

See `docs/setup-credentials.md` for detailed bot setup instructions.

## Quick start — new project

Open Claude Code in the project directory and run:

```
/cloglog init
```

The skill walks you through nine steps:

1. **Project name and quality gate detection** — auto-detects `make quality`, `npm run lint && npm test`, `cargo clippy && cargo test`, etc. from the repo's manifests; you can override.
2. **Backend bootstrap (two-phase)** — POSTs to `/api/v1/projects` with your `DASHBOARD_SECRET`, then writes `project_id` + `backend_url` into `.cloglog/config.yaml`. **Single-project machine**: the API key is written to `~/.cloglog/credentials` (chmod 600). **Multi-project machine**: the existing `~/.cloglog/credentials` is preserved and the new key is *printed once* — you must `export CLOGLOG_API_KEY=<key>` (or add it to `.envrc` / shell RC) before restarting. After Step 2 the skill stops and asks you to **restart Claude Code** so the MCP server reloads with the new credentials.
3. **MCP server configuration** — writes the `mcpServers.cloglog` entry into `.mcp.json` at the project root (the file Claude Code actually loads MCP servers from) and the matching `SessionStart` hook into `.claude/settings.json`, both pointing at resolved absolute paths because `${CLAUDE_PLUGIN_ROOT}` does not expand for SessionStart hooks. Re-running init auto-repairs the legacy layout where `mcpServers` lived in `.claude/settings.json` (T-344).
4. **`.cloglog/` directory setup** — writes `config.yaml` (see shape below) and a tech-stack-aware `on-worktree-create.sh` (uv sync / npm install / cargo build / etc.). The `worktree_scopes:` template is emitted **commented out** because its keys must match your launcher's worktree-naming convention; uncomment and fill in once you've launched a worktree or two.
5. **CLAUDE.md workflow rules** — appends a `## Workflow Discipline (cloglog)` section covering task lifecycle, quality-gate enforcement, worktree boundaries, and the feature pipeline (spec → plan → impl).
6. **GitHub bot identity** — checks for the remote, the PEM, and that the App installation has access to *this* repo. Each missing piece prints the exact remediation steps and lets init continue (agent PRs just won't work until fixed).
7. **Codex PR review setup** — copies `templates/codex-review-schema.json` to `.github/codex/review-schema.json`, generates a tech-stack-tailored `.github/codex/prompts/review.md`, and appends a `## Review guidelines` section to AGENTS.md (creating an AGENTS.md ↔ CLAUDE.md symlink if only one exists so both Claude and Codex read the same file).
8. **Gitignore + stage** — adds `.cloglog/inbox` to `.gitignore` and `git add`s everything init produced (init never commits — you decide when).
9. **Summary** — prints a table of what was configured and flags anything left for you (bot setup, key export, etc.).

**Re-running init is safe.** It detects an existing `project_id` in `.cloglog/config.yaml` and skips the bootstrap (no duplicate project on the backend). Use re-runs to pick up new template keys, refresh paths, or finish steps you skipped on the first pass.

### `.cloglog/config.yaml` shape

```yaml
project_name: my-project
project_id: <UUID from POST /api/v1/projects>
backend_url: http://127.0.0.1:8001
quality_command: make quality

# Consumers: auto_merge_gate.py, scripts/check-demo.sh, scripts/preflight.sh,
# the demo / close-wave / github-bot / launch skills. Init MUST emit all four.
dashboard_key: my-project-dashboard-dev
webhook_tunnel_name: my-project-webhooks
prod_worktree_path: ../my-project-prod   # only meaningful with a separate prod branch

# Final-stage reviewer bots only — a two-stage opencode → codex pipeline lists
# only the codex bot here so stage-A approvals fall through to in_progress.
reviewer_bot_logins:
  - cloglog-codex-reviewer[bot]

# Single-line regex of paths whose changes never need a stakeholder demo.
demo_allowlist_paths: '^docs/|^CLAUDE\.md|^\.claude/|^\.cloglog/|^scripts/|^\.github/|^tests/|^Makefile$|^plugins/[^/]+/(hooks|skills|agents|templates)/|^pyproject\.toml$|^ruff\.toml$|package-lock\.json$|\.lock$'

# protect-worktree-writes hook scope map. Hook strips `wt-` from the worktree
# basename and looks up the remainder here (prefix-matched). Keys must match
# your launcher's naming convention. Init emits commented-out — uncomment after
# you've settled on a convention.
# worktree_scopes:
#   backend: [src/, tests/]
#   frontend: [frontend/src/, frontend/tests/]
```

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
