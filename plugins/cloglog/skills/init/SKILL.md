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

Check if `.claude/settings.json` exists in the project. If the cloglog MCP server is not configured, add it. Also inject the `SessionStart` hook for main agent bootstrapping (register + inbox monitor).

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "<absolute-path-to-project>/plugins/cloglog/hooks/session-bootstrap.sh",
            "timeout": 5
          }
        ]
      }
    ]
  },
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

**Important:** The `SessionStart` hook must use an absolute path to the bootstrap script — `${CLAUDE_PLUGIN_ROOT}` does not resolve for `SessionStart` hooks in plugin settings.json (only project-level settings work). This is why init injects it into the project settings.

If the file already has a cloglog MCP entry or SessionStart hook, update rather than duplicating.

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
cd "${WORKTREE_PATH:?WORKTREE_PATH must be set}"
uv sync
```

**Node.js** (detected by `package.json`):
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "${WORKTREE_PATH:?WORKTREE_PATH must be set}"
npm install
```

**Rust** (detected by `Cargo.toml`):
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "${WORKTREE_PATH:?WORKTREE_PATH must be set}"
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

## Step 6: GitHub & Bot Identity Setup

The cloglog workflow requires a GitHub repo and a GitHub App bot identity for all git operations. Check three things in order.

### 6a. Check if the project has a GitHub remote

```bash
git remote get-url origin 2>/dev/null
```

**If no remote exists**, the code hasn't been pushed to GitHub yet. Guide the user:

> **No GitHub remote found.** Before agents can create PRs, this project needs a GitHub repository.
>
> 1. Create a repo on GitHub (or use `gh repo create`)
> 2. Add the remote: `git remote add origin git@github.com:<owner>/<repo>.git`
> 3. Push: `git push -u origin main`
> 4. Run `/cloglog init` again to continue setup.

Record in the summary: `GitHub repo: not configured`. The init can continue for everything else — the bot check will be skipped.

### 6b. Check if the GitHub App bot exists

Look for:
- `~/.agent-vm/credentials/github-app.pem` on disk
- `scripts/gh-app-token.py` in this project OR in any other project under `~/code/`

**If the PEM exists** (bot has been set up before):

Copy the token script if this project doesn't have it yet:
```bash
if [[ ! -f scripts/gh-app-token.py ]]; then
  OTHER=$(find ~/code -path "*/scripts/gh-app-token.py" -not -path "$(pwd)/*" 2>/dev/null | head -1)
  if [[ -n "$OTHER" ]]; then
    mkdir -p scripts
    cp "$OTHER" scripts/gh-app-token.py
    chmod +x scripts/gh-app-token.py
  fi
fi
```

**If the PEM does not exist** (first-time setup):

> **GitHub Bot Identity Required**
>
> The cloglog workflow requires a GitHub App bot for all git operations. This ensures agent work is attributed to the bot, not your personal account.
>
> **Setup steps:**
> 1. Create a GitHub App at https://github.com/settings/apps/new
>    - Name: something like "cloglog-bot"
>    - Permissions: Contents (read/write), Pull requests (read/write), Issues (read/write)
>    - Install it on the repositories you want to manage
> 2. Generate a private key and save it to `~/.agent-vm/credentials/github-app.pem`
> 3. Note the App ID and Installation ID — update `scripts/gh-app-token.py` accordingly
>
> Run `/cloglog init` again once the bot is set up.

Record in the summary: `GitHub bot: needs setup`. The init can continue — agents just won't be able to create PRs until this is done.

### 6c. Verify bot has access to THIS repo

Only run this if both the remote and the bot exist:

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py 2>/dev/null)
if [[ -n "$BOT_TOKEN" ]]; then
  REPO=$(git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
  if GH_TOKEN="$BOT_TOKEN" gh repo view "$REPO" --json name -q .name 2>/dev/null; then
    echo "Bot has access to this repo"
  else
    echo "Bot does NOT have access to this repo"
  fi
fi
```

**If the bot does not have access:**

> **GitHub App not installed on this repository.**
>
> The bot exists but doesn't have permission for this repo. Fix:
> 1. Go to https://github.com/settings/installations
> 2. Click your GitHub App installation → "Configure"
> 3. Under "Repository access", add this repository
>
> This is the only step needed — the bot credentials are already set up.

Record in the summary: `GitHub bot: needs repo access`.

## Step 7: Set Up Automated PR Review (Codex)

The cloglog plugin includes templates for automated PR review using OpenAI Codex CLI. Set up the review infrastructure:

### 7a. Copy review schema and generate project-specific review prompt

```bash
PLUGIN_ROOT="<path to plugins/cloglog>"
mkdir -p .github/codex/prompts

cp "${PLUGIN_ROOT}/templates/codex-review-schema.json" .github/codex/review-schema.json
```

**Generate the review prompt — do NOT just copy the template.** The template at `${PLUGIN_ROOT}/templates/codex-review-prompt.md` contains the generic structure. Read it, then generate `.github/codex/prompts/review.md` by adding project-specific verification steps based on the detected tech stack:

**Python/FastAPI** (detected by `pyproject.toml` + FastAPI in deps):
- Add: "Read the Pydantic request/response schema. Check if `model_dump(exclude_unset=True)` silently drops fields."
- Add: "Check route registration in the app factory — is the new router included?"
- Add: "If a migration is added, verify the Alembic revision chain."
- Add: "Check `tests/conftest.py` — are new models imported for table creation?"

**Node.js/TypeScript** (detected by `package.json` + `tsconfig.json`):
- Add: "Check `package.json` — are new dependencies added with appropriate version ranges?"
- Add: "If the diff adds types, verify they're exported from the barrel file (index.ts)."
- Add: "Check for any `as any` type casts that bypass type safety."

**React frontend** (detected by React in deps):
- Add: "Read the component being modified. Are props properly typed?"
- Add: "If API types are used, verify they're imported from the generated types file, not hand-written."
- Add: "Check for missing cleanup in useEffect hooks."

**Rust** (detected by `Cargo.toml`):
- Add: "Check if new `unwrap()` calls exist — should they use `?` or `.expect()` instead?"
- Add: "Verify new public API items have documentation."

**DDD/bounded contexts** (detected by AGENTS.md mentioning contexts or `docs/ddd-context-map.md` existing):
- Add: "Read the context map. Verify no imports cross bounded context boundaries."

**Mixed stacks**: combine the relevant sections.

The generated prompt should keep the generic structure (read full file, trace imports, verify tests, cite evidence, don't report surface bugs) and ADD the tech-stack-specific verification steps.

### 7b. Add review guidelines to AGENTS.md

Check if the project has an `AGENTS.md` (or `CLAUDE.md`). If it has a `## Review guidelines` section already, skip this. Otherwise, append the review guidelines fragment:

```bash
GUIDELINES="${PLUGIN_ROOT}/templates/review-guidelines-fragment.md"
TARGET="AGENTS.md"
if [[ ! -f "$TARGET" ]]; then
  TARGET="CLAUDE.md"
fi
if [[ -f "$TARGET" ]] && ! grep -q "## Review guidelines" "$TARGET"; then
  echo "" >> "$TARGET"
  cat "$GUIDELINES" >> "$TARGET"
fi
```

The `## Review guidelines` section is specifically recognized by Codex CLI during reviews. Projects should customize these rules for their own architecture.

### 7c. AGENTS.md / CLAUDE.md symlink

If the project has `CLAUDE.md` but no `AGENTS.md`, create a symlink so both Claude Code and Codex read the same file:

```bash
if [[ -f "CLAUDE.md" ]] && [[ ! -f "AGENTS.md" ]] && [[ ! -L "CLAUDE.md" ]]; then
  mv CLAUDE.md AGENTS.md
  ln -s AGENTS.md CLAUDE.md
fi
```

If `AGENTS.md` exists but `CLAUDE.md` doesn't, create the reverse symlink:

```bash
if [[ -f "AGENTS.md" ]] && [[ ! -f "CLAUDE.md" ]]; then
  ln -s AGENTS.md CLAUDE.md
fi
```

## Step 8: Gitignore and Add to Git

Add `.cloglog/inbox` to `.gitignore` (the inbox file is runtime state, not source):

```bash
echo '.cloglog/inbox' >> .gitignore
```

Then stage the config files:

```bash
git add .cloglog/ .github/codex/ .gitignore
```

If CLAUDE.md/AGENTS.md was modified, add that too. If `scripts/gh-app-token.py` was created, add that too. Do not commit automatically — let the user decide when to commit.

## Step 9: Summary

Present what was configured:

| Item | Value |
|------|-------|
| Project name | `<name>` |
| Quality command | `<command>` |
| Tech stack | Python/Node/Rust/Mixed |
| Config location | `.cloglog/config.yaml` |
| MCP configured | yes/no (+ instructions if manual setup needed) |
| SessionStart hook | injected into `.claude/settings.json` |
| CLAUDE.md | updated/created |
| GitHub bot | configured/needs setup |

Remind the user to:
1. Set their `CLOGLOG_API_KEY` in `.claude/settings.json` (if not already set)
2. **Set up the GitHub bot** if not yet configured (see Step 6 output)
3. Run `git commit` to save the configuration
4. Start the cloglog backend if not running

**If the GitHub bot is not configured**, warn prominently:
> **WARNING: GitHub bot is not configured.** Without it, agent PRs and pushes will use your personal GitHub identity. Follow the setup instructions above before launching agents.
