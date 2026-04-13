---
name: init
description: Initialize a project for cloglog management. Detects tech stack, configures MCP server, creates project config, and injects workflow rules.
user-invocable: true
---

# Initialize Project for Cloglog

Set up a project to be managed by the cloglog Kanban dashboard. This skill is idempotent — re-running it updates configuration without duplicating anything.

**Usage:**
```
/cloglog init
/cloglog init my-project-name
```

Arguments: `$ARGUMENTS` — optional project name. If omitted, the skill will ask or default to the directory name.

## Step 1: Gather Project Info

### 1a. Project name

If `$ARGUMENTS` provides a name, use it. Otherwise, default to the current directory name:
```bash
basename $(pwd)
```

Ask the user to confirm or override.

### 1b. Detect quality gate command

Check for common patterns:
- `Makefile` with a `quality` target — use `make quality`
- `Makefile` with a `check` or `lint` target — use that
- `package.json` with a `lint` or `test` script — use `npm run lint && npm test`
- `Cargo.toml` — use `cargo clippy && cargo test`
- `pyproject.toml` — use `uv run pytest && uv run ruff check`

If auto-detection finds something, present it and ask the user to confirm or override. If nothing is found, ask the user for their quality gate command.

### 1c. Detect backend URL

Check if a cloglog backend is already running or configured. Default to `http://localhost:8000`.

## Step 2: Register Project on Board

Call `mcp__cloglog__get_board` to check if the project already exists. If not, the user will need to register it through the backend API or MCP tools.

## Step 3: Configure MCP Server

Check if `.claude/settings.json` exists in the project. If the cloglog MCP server is not configured, add it:

```json
{
  "mcpServers": {
    "cloglog": {
      "command": "node",
      "args": ["/path/to/mcp-server/dist/index.js"],
      "env": {
        "CLOGLOG_BACKEND_URL": "http://localhost:8000",
        "CLOGLOG_API_KEY": "<project-api-key>"
      }
    }
  }
}
```

If the file already has a cloglog entry, update it rather than duplicating.

## Step 4: Create `.cloglog/` Configuration Directory

### 4a. `config.yaml`

```yaml
project_name: <name>
backend_url: http://localhost:8000
quality_command: <detected or user-provided command>
```

If `.cloglog/config.yaml` already exists, update fields rather than overwriting.

### 4b. `on-worktree-create.sh`

Detect the tech stack and generate the appropriate setup script:

**Python with uv** (detected by `pyproject.toml` + `uv.lock` or `[tool.uv]`):
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$1"
uv sync
```

**Node.js** (detected by `package.json`):
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$1"
npm install
```

**Rust** (detected by `Cargo.toml`):
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$1"
cargo build
```

**Mixed** (multiple detected): combine the relevant commands.

**None detected**: create an empty script with a comment:
```bash
#!/usr/bin/env bash
# Add project-specific worktree setup commands here
```

Make the script executable: `chmod +x .cloglog/on-worktree-create.sh`

### 4c. `on-worktree-destroy.sh` (if needed)

Only create this if the project needs teardown (e.g., database cleanup). Default to an empty script:

```bash
#!/usr/bin/env bash
# Add project-specific worktree teardown commands here
# Examples: drop worktree database, kill port processes
```

Make executable: `chmod +x .cloglog/on-worktree-destroy.sh`

## Step 5: Inject Workflow Rules into CLAUDE.md

If the project has a `CLAUDE.md`, append workflow rules. If not, create one. The rules to inject:

```markdown
## Workflow Discipline (cloglog)

This project is managed by the cloglog Kanban dashboard. Follow these rules:

### Task Lifecycle
- Tasks flow through: backlog -> in_progress -> testing -> review -> done
- Always call `mcp__cloglog__start_task` before beginning work
- Always call `mcp__cloglog__update_task_status` when transitioning
- Create PRs using the github-bot skill for bot identity
- Move to review with the PR URL immediately after creating the PR

### Quality Gate
- Run the quality gate before every commit: `<quality_command>`
- This is enforced by a hook — commits are blocked if it fails

### Worktree Agents
- Each agent works in an isolated worktree
- Only touch files in your assigned area
- Register on start, unregister on completion
- Communicate via PR comments, not terminal

### Feature Pipeline
- Features (F-*) follow: spec -> plan -> impl
- Each phase has its own task on the board
- Spec and impl require PRs; plan is committed directly
```

**Idempotency**: Check if the `## Workflow Discipline (cloglog)` section already exists. If so, replace it rather than appending a duplicate.

## Step 6: GitHub Bot Identity Setup

The cloglog workflow requires all git pushes and PRs to go through a GitHub App bot identity. This prevents agents from pushing as the user's personal account.

### 6a. Check if the GitHub App is already configured

Look for:
- `scripts/gh-app-token.py` in the project
- `~/.agent-vm/credentials/github-app.pem` on disk

If both exist, the bot is ready. Skip to Step 7.

### 6b. If not configured, guide the user

Tell the user:

> **GitHub Bot Identity Required**
>
> The cloglog workflow requires a GitHub App bot for all git operations (push, PR creation, comments). This ensures agent work is attributed to the bot, not your personal account.
>
> **If you already have a GitHub App configured for another cloglog project:**
> The same bot works across all projects — you just need to grant it access to this repo.
> 1. Go to your GitHub App settings → Install App → select this repository
> 2. Copy `scripts/gh-app-token.py` from your existing project (or the plugin will create a symlink)
>
> **If this is your first cloglog project:**
> 1. Create a GitHub App at https://github.com/settings/apps/new
>    - Name: something like "cloglog-bot"
>    - Permissions: Contents (read/write), Pull requests (read/write), Issues (read/write)
>    - Install it on the repositories you want to manage
> 2. Generate a private key (PEM) and save it to `~/.agent-vm/credentials/github-app.pem`
> 3. Note the App ID and Installation ID
>
> Run `/cloglog init` again once the bot is set up.

### 6c. Create or link `scripts/gh-app-token.py`

If the script doesn't exist in this project but exists in another cloglog project, offer to copy or symlink it:

```bash
# Check if it exists elsewhere
OTHER=$(find ~/code -path "*/scripts/gh-app-token.py" -not -path "$(pwd)/*" 2>/dev/null | head -1)
if [[ -n "$OTHER" ]]; then
  mkdir -p scripts
  cp "$OTHER" scripts/gh-app-token.py
  chmod +x scripts/gh-app-token.py
fi
```

### 6d. Verify bot access to this repo

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py 2>/dev/null)
if [[ -n "$BOT_TOKEN" ]]; then
  REPO=$(git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
  GH_TOKEN="$BOT_TOKEN" gh repo view "$REPO" --json name -q .name 2>/dev/null && echo "Bot has access to this repo" || echo "WARNING: Bot does not have access to this repo. Install the GitHub App on this repository."
fi
```

If verification fails, warn the user that PRs will fall back to their personal identity until the bot is configured.

## Step 7: Add `.cloglog/` to Git

```bash
git add .cloglog/
```

If CLAUDE.md was modified, add that too. If `scripts/gh-app-token.py` was created, add that too. Do not commit automatically — let the user decide when to commit.

## Step 8: Summary

Present what was configured:

| Item | Value |
|------|-------|
| Project name | `<name>` |
| Quality command | `<command>` |
| Tech stack | Python/Node/Rust/Mixed |
| Config location | `.cloglog/config.yaml` |
| MCP configured | yes/no (+ instructions if manual setup needed) |
| CLAUDE.md | updated/created |
| GitHub bot | configured/needs setup |

Remind the user to:
1. Set their `CLOGLOG_API_KEY` in `.claude/settings.json` (if not already set)
2. **Set up the GitHub bot** if not yet configured (see Step 6 output)
3. Run `git commit` to save the configuration
4. Start the cloglog backend if not running

**If the GitHub bot is not configured**, warn prominently:
> **WARNING: GitHub bot is not configured.** Without it, agent PRs and pushes will use your personal GitHub identity. Follow the setup instructions above before launching agents.
