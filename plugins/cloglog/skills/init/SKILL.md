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

## Prerequisites

Before running `/cloglog init`, ensure the following are satisfied.

**1. Plugin installed.** The cloglog plugin must be installed in Claude Code:

```bash
claude plugins install /path/to/plugins/cloglog
```

After install, restart Claude Code. Confirm with `/help` — the cloglog skills should appear.

**2. Backend running.** The cloglog backend must be accessible (default: `http://127.0.0.1:8001`). Step 2 makes a direct HTTP call to bootstrap the project.

Verify: `curl -sf http://127.0.0.1:8001/health`

**3. `DASHBOARD_SECRET` exported.** Step 2 authenticates the project-creation call with your dashboard key. Export it before starting:

```bash
export DASHBOARD_SECRET=<value from your backend's .env>
```

Add to `~/.bashrc` or `~/.zshenv` so every Claude Code session inherits it.

**4. GitHub App credentials (optional).** Steps 6–7 configure bot identity for agent PRs. You can run init without them and complete the bot setup later — agents just won't be able to push or create PRs until configured. See `${CLAUDE_PLUGIN_ROOT}/docs/setup-credentials.md`.

**Re-running init** is safe. If this project is already bootstrapped (`.cloglog/config.yaml` has a `project_id` and `~/.cloglog/credentials` has a key), prerequisite 3 (`DASHBOARD_SECRET`) is no longer needed — the project already exists on the backend. Prerequisite 4 (GitHub App) is **host-local** and must be satisfied independently on every machine: `~/.agent-vm/credentials/github-app.pem` (the PEM secret), and `gh_app_id` / `gh_app_installation_id` in the gitignored `.cloglog/local.yaml` (non-secret operator-specific identifiers — T-348). `gh-app-token.py` reads them on every invocation.

**Auto-repair on re-run.** Earlier versions of this skill wrote the `mcpServers.cloglog` block to `.claude/settings.json`. Claude Code does not load MCP servers from that file — they must live in `.mcp.json` at the project root. Re-running init detects that legacy layout and migrates the block: it moves `mcpServers.cloglog` into `.mcp.json` and strips the stale `mcpServers` key from `.claude/settings.json`. The migration is idempotent — a second re-run is a no-op.

**Auto-repair: empty `repo_url` on the backend.** Step 6a now backfills the project's `repo_url` on the backend whenever a GitHub remote is configured locally. The detected URL is **canonicalized** to `https://github.com/<owner>/<repo>` (no `.git`, no SSH form, no trailing slash) before being written via `mcp__cloglog__update_project`. The backend's webhook router and codex review engine resolve a project by `Project.repo_url.endswith(<repo_full_name>)` — a row stored as `git@github.com:owner/repo.git` would never match, so canonical bytes on disk are load-bearing. If the project's `repo_url` is already canonical, the call is a no-op (the backend's `update_project` re-normalizes idempotently). If the project was created via the pre-T-346 init flow with an empty `repo_url`, this is the repair path.

**`mcp__cloglog__update_project` does NOT require a prior `mcp__cloglog__register_agent`.** Other MCP tools (`start_task`, `get_my_tasks`, etc.) demand registration because they're scoped to a worktree session. `update_project` operates on the *project* itself, identified by the API key the MCP server was started with — so the server lazily resolves `project_id` via `GET /api/v1/gateway/me` on first use. Init can call `update_project` from a fresh shell (no worktree, no agent registered) and it works.

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

Check if a cloglog backend is already running or configured. Default to `http://127.0.0.1:8001` (the prod backend). Use `127.0.0.1` rather than `localhost` — on IPv6-first hosts `localhost` resolves to `::1` and the Node MCP server fails with `ECONNREFUSED`. Port 8000 is reserved for cloglog's own dev server.

## Step 2: Bootstrap Project on Backend (Two-Phase)

On a fresh project the MCP server has no credentials yet, so `mcp__cloglog__*` tools are
unavailable. This step uses a direct HTTP call to create the project and write credentials
before restarting. On a subsequent run (after restart) it detects the repo-local `project_id`
and skips straight to Step 3.

### Phase 1 — detect existing bootstrap

```bash
BACKEND_URL="${CLOGLOG_BACKEND_URL:-http://127.0.0.1:8001}"

# Use project-local config if already written.
# Use the canonical scalar-parser pipeline from plugins/cloglog/hooks/lib/parse-yaml-scalar.sh:
# strips surrounding quotes and trailing comments, takes first match.
if [ -f .cloglog/config.yaml ]; then
  _cfg_backend=$(grep '^backend_url:' .cloglog/config.yaml 2>/dev/null | head -n1 \
    | sed 's/^backend_url:[[:space:]]*//' \
    | sed 's/[[:space:]]*#.*$//' \
    | tr -d '"'"'")
  [ -n "$_cfg_backend" ] && BACKEND_URL="$_cfg_backend"
fi

# Check for a repo-local project_id — this is the repo-scoped identity signal.
# NOTE: we also check for credentials below. project_id alone is not enough because
# cloning a repo that has .cloglog/config.yaml checked in (with project_id) but no
# local ~/.cloglog/credentials would cause the MCP server to hard-fail at startup.
EXISTING_PROJECT_ID=""
if [ -f .cloglog/config.yaml ]; then
  EXISTING_PROJECT_ID=$(grep '^project_id:' .cloglog/config.yaml | sed 's/^project_id: *//')
fi

# Check for credentials (env var takes priority, then per-project file
# from T-382, then legacy global file — matches mcp-server/src/credentials.ts
# loadApiKey resolution exactly).
EXISTING_CREDS=""
if [ -n "${CLOGLOG_API_KEY:-}" ]; then
  EXISTING_CREDS="env"
else
  # Derive the slug the resolver will look for. Same precedence as
  # resolveProjectSlug(): config `project:` field first, basename fallback.
  EXISTING_SLUG=""
  if [ -f .cloglog/config.yaml ] && grep -q '^project:' .cloglog/config.yaml; then
    EXISTING_SLUG=$(grep '^project:' .cloglog/config.yaml | head -n1 \
                    | sed 's/^project:[[:space:]]*//' \
                    | sed 's/[[:space:]]*#.*$//' \
                    | tr -d '"'"'")
  fi
  [ -z "$EXISTING_SLUG" ] && EXISTING_SLUG=$(basename "$(pwd)")
  if [ -n "$EXISTING_SLUG" ] \
      && [ -f "${HOME}/.cloglog/credentials.d/${EXISTING_SLUG}" ] \
      && grep -q '^CLOGLOG_API_KEY=' "${HOME}/.cloglog/credentials.d/${EXISTING_SLUG}"; then
    EXISTING_CREDS="per-project"
  elif [ -f ~/.cloglog/credentials ] && grep -q '^CLOGLOG_API_KEY=' ~/.cloglog/credentials; then
    EXISTING_CREDS="file"
  fi
fi
```

**If both `EXISTING_PROJECT_ID` is non-empty AND `EXISTING_CREDS` is non-empty**, this
project is fully bootstrapped. Skip to Step 3 — the MCP server picked up the key at startup
and `mcp__cloglog__*` tools are available.

**If `EXISTING_PROJECT_ID` is non-empty but `EXISTING_CREDS` is empty** (e.g. the repo was
cloned to a new machine), stop with a repair instruction:

> **Credentials missing for an existing project.**
>
> `.cloglog/config.yaml` has `project_id: <id>` but no `CLOGLOG_API_KEY` is available.
> The MCP server cannot start without the project API key.
>
> To repair:
> 1. Obtain the project API key (rotate with `scripts/rotate-project-key.py` if lost).
> 2. Write it. **Choose the right destination — writing the wrong file on a
>    multi-project host clobbers another project's key (T-382):**
>
>    ```bash
>    # Derive THIS project's slug exactly the way the resolver does
>    # (config field first, basename fallback, [A-Za-z0-9._-]+ validator).
>    SLUG=$(grep '^project:' .cloglog/config.yaml 2>/dev/null | head -n1 \
>            | sed 's/^project:[[:space:]]*//; s/[[:space:]]*#.*$//' \
>            | tr -d '"'"'")
>    [ -z "$SLUG" ] && SLUG=$(basename "$(pwd)")
>
>    if [ -f ~/.cloglog/credentials ] && grep -q '^CLOGLOG_API_KEY=' ~/.cloglog/credentials; then
>      # Multi-project host: another project owns ~/.cloglog/credentials.
>      # Write to ~/.cloglog/credentials.d/<slug> so the legacy file stays
>      # intact for that other project.
>      mkdir -p ~/.cloglog/credentials.d
>      printf 'CLOGLOG_API_KEY=%s\n' "<key>" > ~/.cloglog/credentials.d/"$SLUG"
>      chmod 600 ~/.cloglog/credentials.d/"$SLUG"
>    else
>      # Single-project host: use the legacy global file.
>      mkdir -p ~/.cloglog
>      printf 'CLOGLOG_API_KEY=%s\n' "<key>" > ~/.cloglog/credentials
>      chmod 600 ~/.cloglog/credentials
>    fi
>    ```
> 3. Restart Claude Code, then run `/cloglog init` again.
>
> Do NOT re-run the bootstrap (Phase 2) — the project already exists; creating another
> one will register a duplicate.

### Phase 2 — create project via admin HTTP (fresh setup only)

If no repo-local `project_id` exists, create the project directly against the backend.

**Multi-project credentials check.** Since T-382 the MCP loader resolves
`CLOGLOG_API_KEY` from env → `~/.cloglog/credentials.d/<project_slug>` →
`~/.cloglog/credentials`. On a host that already runs another cloglog
project, write the new key to its **own** per-project file under
`credentials.d/`; the legacy global file is left untouched so the other
project keeps working unchanged. On a fresh single-project host, write to
the legacy global file (one less file to manage):

```bash
MULTI_PROJECT=false
if [ -z "${CLOGLOG_API_KEY:-}" ] && [ -f ~/.cloglog/credentials ] \
    && grep -q '^CLOGLOG_API_KEY=' ~/.cloglog/credentials; then
  MULTI_PROJECT=true
  echo "NOTE: ~/.cloglog/credentials already has a CLOGLOG_API_KEY (another project)."
  echo "The new project's API key will be written to ~/.cloglog/credentials.d/<slug>"
  echo "instead of overwriting the global file (T-382 per-project resolution)."
fi
```

Proceed:

1. **Locate the dashboard key.** The backend validates it against the `DASHBOARD_SECRET`
   setting (see `src/shared/config.py`). Read it from the environment — the variable name
   must match whatever the operator set as `DASHBOARD_SECRET` in their backend's `.env`:

   ```bash
   DASHBOARD_KEY="${DASHBOARD_SECRET:-}"
   ```

   If it is empty, ask the operator:

   > **Admin credential required.** To bootstrap this project on the cloglog backend,
   > provide your dashboard key (the value of `DASHBOARD_SECRET` in your backend's
   > environment). This is a one-time step — after setup the MCP server authenticates
   > automatically.

2. **Create the project:**

   ```bash
   PROJECT_NAME="<name from Step 1>"

   RESPONSE=$(curl -sf -X POST \
     -H "Content-Type: application/json" \
     -H "X-Dashboard-Key: ${DASHBOARD_KEY}" \
     -d "{\"name\": \"${PROJECT_NAME}\", \"description\": \"\"}" \
     "${BACKEND_URL}/api/v1/projects")

   if [ $? -ne 0 ] || [ -z "$RESPONSE" ]; then
     echo "ERROR: Could not reach backend at ${BACKEND_URL}. Is it running?"
     exit 1
   fi

   PROJECT_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")
   API_KEY=$(echo "$RESPONSE"    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['api_key'])")
   ```

   > **Note:** Each call to `POST /api/v1/projects` creates a new project. If init is
   > re-run after a partial bootstrap (e.g., credentials were written but the operator
   > never restarted), detect the existing project via `EXISTING_PROJECT_ID` above and
   > skip this step — do not re-post the same project name.

3. **Write credentials** (shown once — backend stores only a hash):

   ```bash
   # T-382 — derive a slug for the per-project credential file. Same
   # validator as mcp-server/src/credentials.ts and the launch SKILL
   # _project_slug helper: keep [A-Za-z0-9._-], replace anything else
   # with `-`. The result is what the resolver uses to find the key
   # for THIS project, so it must be deterministic from PROJECT_NAME.
   PROJECT_SLUG=$(printf '%s' "$PROJECT_NAME" | tr -c '[:alnum:]._-' '-' | sed 's/^-*//; s/-*$//')

   # Backend project names are unconstrained (src/board/schemas.py: any
   # str), so a name like "!!!" or "***" produces an empty slug. Empty
   # would write CLOGLOG_API_KEY to ~/.cloglog/credentials.d/ (the
   # directory itself) and seed `project:` blank — both leave the new
   # project unable to authenticate after restart. Fall back to the
   # checkout basename, validated the same way; if THAT is also empty,
   # halt with an explicit message rather than write garbage.
   if [ -z "$PROJECT_SLUG" ]; then
     PROJECT_SLUG=$(basename "$(pwd)" | tr -c '[:alnum:]._-' '-' | sed 's/^-*//; s/-*$//')
   fi
   if [ -z "$PROJECT_SLUG" ]; then
     echo "ERROR: cannot derive a slug-safe identifier from PROJECT_NAME=${PROJECT_NAME}" >&2
     echo "       or basename $(pwd). The per-project credential file path requires" >&2
     echo "       a non-empty match against [A-Za-z0-9._-]+. Pick a project name with" >&2
     echo "       at least one alphanumeric/dot/underscore/hyphen character and re-run." >&2
     exit 1
   fi

   if [ "$MULTI_PROJECT" = "false" ]; then
     # Single-project host: write the legacy global file. Backward
     # compatible with operators who never adopt credentials.d/.
     mkdir -p ~/.cloglog
     printf 'CLOGLOG_API_KEY=%s\n' "$API_KEY" > ~/.cloglog/credentials
     chmod 600 ~/.cloglog/credentials
   else
     # Multi-project host: write to ~/.cloglog/credentials.d/<slug> so
     # the other project's key stays in ~/.cloglog/credentials and the
     # T-382 resolver routes the right key to the right project.
     mkdir -p ~/.cloglog/credentials.d
     printf 'CLOGLOG_API_KEY=%s\n' "$API_KEY" > "${HOME}/.cloglog/credentials.d/${PROJECT_SLUG}"
     chmod 600 "${HOME}/.cloglog/credentials.d/${PROJECT_SLUG}"
   fi
   ```

4. **Write `project`, `project_id`, and `backend_url` to config.** Seeding all three
   now ensures the second run reads the correct backend URL from config (not only from
   `$CLOGLOG_BACKEND_URL` which may not be set after restart) AND that the per-project
   credential resolver (T-382) finds the slug source on first restart — without `project:`
   in `.cloglog/config.yaml`, the SessionEnd hook and MCP server fall back to
   `basename($PROJECT_ROOT)` for the slug, which matches the credentials.d/<slug> file
   only by accident. Step 4a will write the full config later; these three keys bootstrap
   the re-run detection and the credential lookup:

   ```bash
   mkdir -p .cloglog

   # project — slug source for ~/.cloglog/credentials.d/<slug> (T-382). The
   # resolver validates against [A-Za-z0-9._-]+ so we write the same slug the
   # credentials.d file was named with, not the raw PROJECT_NAME.
   if [ -f .cloglog/config.yaml ] && grep -q '^project:' .cloglog/config.yaml; then
     sed -i "s/^project:.*/project: ${PROJECT_SLUG}/" .cloglog/config.yaml
   else
     printf 'project: %s\n' "$PROJECT_SLUG" >> .cloglog/config.yaml
   fi

   # project_id — update in place or append (never use >> alone: scalar parser
   # returns first match, so a duplicate key silently shadows the new value).
   if [ -f .cloglog/config.yaml ] && grep -q '^project_id:' .cloglog/config.yaml; then
     sed -i "s/^project_id:.*/project_id: ${PROJECT_ID}/" .cloglog/config.yaml
   else
     printf 'project_id: %s\n' "$PROJECT_ID" >> .cloglog/config.yaml
   fi

   # backend_url — persist so Step 3/4 and hooks use the same URL after restart
   if [ -f .cloglog/config.yaml ] && grep -q '^backend_url:' .cloglog/config.yaml; then
     sed -i "s|^backend_url:.*|backend_url: ${BACKEND_URL}|" .cloglog/config.yaml
   else
     printf 'backend_url: %s\n' "$BACKEND_URL" >> .cloglog/config.yaml
   fi
   ```

5. **Request restart.** Tell the operator:

   If `MULTI_PROJECT=false` (single-project machine — key written to `~/.cloglog/credentials`):

   > **Project created successfully.**
   >
   > | Field | Value |
   > |-------|-------|
   > | Project ID | `<project_id>` |
   > | API key | written to `~/.cloglog/credentials` |
   >
   > **Next step: restart Claude Code.**
   >
   > The MCP server reads credentials at startup. Please:
   > 1. Exit this Claude Code session (`/exit`)
   > 2. Restart Claude Code in this directory
   > 3. Run `/cloglog init` again — the remaining steps (MCP config, `.cloglog/`,
   >    CLAUDE.md, GitHub bot) will complete on the second run.

   If `MULTI_PROJECT=true` (existing credentials preserved — new key written to its own per-project file):

   > **Project created successfully (multi-project machine).**
   >
   > | Field | Value |
   > |-------|-------|
   > | Project ID | `<project_id>` |
   > | Project slug | `<project_slug>` |
   > | API key | written to `~/.cloglog/credentials.d/<project_slug>` |
   >
   > Your existing `~/.cloglog/credentials` was NOT modified. The MCP server's
   > T-382 resolver picks the per-project file automatically based on the
   > `project:` field in this repo's `.cloglog/config.yaml`. Then:
   > 1. Exit this Claude Code session (`/exit`)
   > 2. Restart Claude Code in this directory
   > 3. Run `/cloglog init` again — the remaining steps complete on the second run.
   >
   > **No env export required** on multi-project hosts since T-382. If you previously
   > kept `export CLOGLOG_API_KEY=...` in your shell RC for a different project, you
   > can remove it — or keep it as an explicit override; env still beats both file
   > sources.

   **Stop here.** Do not proceed to Step 3 — the MCP server is not yet loaded and the
   remaining steps require it or write files that depend on having a valid project_id.

## Step 3: Configure MCP Server

Resolve concrete absolute paths for the bootstrap hook and MCP server entry, then merge them into the **two** files Claude Code reads from:

- `.claude/settings.json` — receives the `SessionStart` hook ONLY. Claude Code does NOT load MCP servers from this file.
- `.mcp.json` (project root) — receives the `mcpServers.cloglog` entry. This is the file Claude Code actually consults for project-scoped MCP servers.

Writing the `mcpServers` block to `.claude/settings.json` is the legacy bug fixed in T-344 — the cloglog MCP server silently failed to start in freshly-init'd projects. Both writes below are idempotent: re-running init updates the cloglog entry in place rather than duplicating it.

Do **not** emit literal `<absolute-path-to-project>`, `<path to plugins/cloglog>`, or `/path/to/mcp-server/dist/index.js` — every path written must be the resolved absolute path on this host.

```bash
# Resolve the bootstrap hook absolute path. SessionStart hooks do NOT expand
# ${CLAUDE_PLUGIN_ROOT}, so we resolve it to a literal absolute path now.
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT must be set — re-run from a Claude Code session with the cloglog plugin installed}"
SESSION_BOOTSTRAP="${PLUGIN_ROOT}/hooks/session-bootstrap.sh"
[ -f "$SESSION_BOOTSTRAP" ] || { echo "ERROR: session-bootstrap.sh not found at $SESSION_BOOTSTRAP"; exit 1; }

# Resolve the MCP server entry. The marketplace bundles it alongside the
# plugin at ${CLAUDE_PLUGIN_ROOT}/../mcp-server/dist/index.js; resolve to an
# absolute path with realpath. If the build is missing, prompt rather than
# writing a placeholder.
MCP_INDEX_CANDIDATE="${PLUGIN_ROOT}/../mcp-server/dist/index.js"
if [ -f "$MCP_INDEX_CANDIDATE" ]; then
  MCP_INDEX="$(cd "$(dirname "$MCP_INDEX_CANDIDATE")" && pwd)/$(basename "$MCP_INDEX_CANDIDATE")"
else
  echo "WARN: mcp-server build not found at $MCP_INDEX_CANDIDATE"
  echo "      Build it: (cd \"${PLUGIN_ROOT}/../mcp-server\" && npm install && npm run build)"
  echo "      Or supply the absolute path to dist/index.js manually."
  read -r -p "Absolute path to mcp-server/dist/index.js: " MCP_INDEX
  [ -f "$MCP_INDEX" ] || { echo "ERROR: $MCP_INDEX does not exist"; exit 1; }
fi

mkdir -p .claude
SESSION_BOOTSTRAP="$SESSION_BOOTSTRAP" \
MCP_INDEX="$MCP_INDEX" \
BACKEND_URL="$BACKEND_URL" \
python3 - <<'PY'
import json, os, pathlib

# --- Step 3 merge: two files, two responsibilities ----------------------------
# `.claude/settings.json`  -> hooks (SessionStart)
# `.mcp.json`              -> mcpServers (cloglog)
#
# T-344: Claude Code does NOT load MCP servers from `.claude/settings.json`.
# The legacy combined merge silently produced a broken project where
# `mcp__cloglog__*` tools never resolved. We now write each block to the file
# Claude Code actually reads it from.

settings_path = pathlib.Path(".claude/settings.json")
mcp_path      = pathlib.Path(".mcp.json")

settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
mcp      = json.loads(mcp_path.read_text())      if mcp_path.exists()      else {}

# Phase 1.5 — auto-repair legacy layout.
# If a previous (broken) init wrote mcpServers.cloglog into settings.json,
# move ONLY the cloglog entry into .mcp.json. Any other mcpServers entries
# (e.g. an operator-maintained `github` or `linear` server) stay put —
# settings.json is the wrong home for `cloglog` specifically, but other
# servers may live there legitimately and we must not silently delete them.
# Idempotent: a clean layout (no cloglog under settings.mcpServers) is a
# no-op for this block.
legacy_servers = settings.get("mcpServers")
if isinstance(legacy_servers, dict) and "cloglog" in legacy_servers:
    legacy_cloglog = legacy_servers.pop("cloglog")
    mcp_servers = mcp.setdefault("mcpServers", {})
    # Prefer the entry already in .mcp.json (operator may have edited it);
    # only seed from settings.json if .mcp.json has no cloglog entry yet.
    mcp_servers.setdefault("cloglog", legacy_cloglog)
    # If cloglog was the only server in settings.mcpServers, drop the now-
    # empty key so a clean post-repair layout has no `mcpServers` in
    # settings.json. Otherwise leave the residual entries untouched.
    if not legacy_servers:
        settings.pop("mcpServers", None)

# Hook write — settings.json owns SessionStart.
hooks = settings.setdefault("hooks", {})
hooks["SessionStart"] = [
    {
        "matcher": "",
        "hooks": [
            {
                "type": "command",
                "command": os.environ["SESSION_BOOTSTRAP"],
                "timeout": 5,
            }
        ],
    }
]

# MCP server write — .mcp.json owns mcpServers.
servers = mcp.setdefault("mcpServers", {})
servers["cloglog"] = {
    "command": "node",
    "args": [os.environ["MCP_INDEX"]],
    "env": {"CLOGLOG_URL": os.environ["BACKEND_URL"]},
}

settings_path.write_text(json.dumps(settings, indent=2) + "\n")
mcp_path.write_text(json.dumps(mcp, indent=2) + "\n")
PY
```

For reference, the resulting shapes are:

`.claude/settings.json` (hooks only — no `mcpServers` key):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "/abs/path/to/plugin/hooks/session-bootstrap.sh",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

`.mcp.json` (mcpServers only — Claude Code's project-scoped MCP config):

```json
{
  "mcpServers": {
    "cloglog": {
      "command": "node",
      "args": ["/abs/path/to/mcp-server/dist/index.js"],
      "env": {
        "CLOGLOG_URL": "http://127.0.0.1:8001"
      }
    }
  }
}
```

> **T-214:** `CLOGLOG_API_KEY` MUST NOT be added to `.mcp.json` or any
> per-project file. The MCP server reads it from the operator's environment
> or from `~/.cloglog/credentials` only. See `${CLAUDE_PLUGIN_ROOT}/docs/setup-credentials.md`.
> The pin is `tests/test_mcp_json_no_secret.py` — the merge above never
> writes `CLOGLOG_API_KEY` into `mcpServers.cloglog.env`.

**Important:** The `SessionStart` hook must use an absolute path to the bootstrap script — `${CLAUDE_PLUGIN_ROOT}` does not resolve for `SessionStart` hooks in plugin settings.json (only project-level settings work). The Python merge above resolves it from the live `${CLAUDE_PLUGIN_ROOT}` and writes the absolute path verbatim. The merge is idempotent — re-running init updates the cloglog entry rather than duplicating it, and migrates the legacy `mcpServers`-in-settings.json layout if present.

## Step 4: Create `.cloglog/` Configuration Directory

### 4a. `config.yaml`

```yaml
# project — slug source for ~/.cloglog/credentials.d/<slug> (T-382). MUST
# be a slug-safe identifier matching [A-Za-z0-9._-]+; the per-project
# credential resolver and the SessionEnd unregister hook both read this
# field. Step 2 already seeded it; do not rename to `project_name:` here
# or the resolver falls back to basename($PROJECT_ROOT) and the
# credentials.d/<slug> lookup misses.
project: <slug>
project_id: <UUID returned by Step 2 — already seeded into config.yaml>
backend_url: <BACKEND_URL detected in Step 1c — e.g. http://127.0.0.1:8001>
quality_command: <detected or user-provided command>

# T-316 keys — every consumer (auto_merge_gate.py, scripts/check-demo.sh,
# scripts/preflight.sh, demo/close-wave/github-bot/launch skills) reads
# from here. Init MUST emit all four; missing keys break the demo gate
# and the auto-merge flow on a fresh repo.
dashboard_key: <project>-dashboard-dev
webhook_tunnel_name: <project>-webhooks
prod_worktree_path: ../<project>-prod   # only meaningful if the project tracks a separate prod branch

# Auto-merge-eligible *final-stage* reviewer bots only — not every reviewer.
# A two-stage pipeline (e.g. opencode → codex) lists only the stage-B bot
# here; stage-A approvals fall through to the standard in_progress flow.
reviewer_bot_logins:
  - <final-stage-reviewer-bot>[bot]   # e.g. cloglog-codex-reviewer[bot]

# Single-line regex of allowlisted paths (paths whose changes never need a
# stakeholder demo). Same shape `scripts/check-demo.sh` parses with
# grep+sed. Cloglog's default below is sensible for most projects:
demo_allowlist_paths: '^docs/|^CLAUDE\.md|^\.claude/|^\.cloglog/|^scripts/|^\.github/|^tests/|^Makefile$|^plugins/[^/]+/(hooks|skills|agents|templates)/|^pyproject\.toml$|^ruff\.toml$|package-lock\.json$|\.lock$'

# T-321 — worktree_scopes: scope-name → list of repo-relative path prefixes
# the protect-worktree-writes hook treats as in-scope for that worktree.
# Init emits this as a *commented-out template* — the scope keys MUST match
# the launcher's worktree-naming convention (the hook strips `wt-` from the
# basename and looks up the remainder in this map, with prefix matching), and
# init has no way to predict that convention. Operators uncomment and adapt
# after wiring up their launch flow.
# worktree_scopes:
#   <scope>: [<path-prefix>/, ...]   # e.g. backend: [src/, tests/]
```

**Important:** Use the `BACKEND_URL` detected in Step 1c (or read from `.cloglog/config.yaml`
which was seeded in Step 2). Do not hard-code `127.0.0.1:8001` — non-default backends must
survive the restart. If Step 2 already wrote `backend_url`, preserve it rather than overwriting
with the default.

`project_id` is already written to `.cloglog/config.yaml` in Step 2 (Phase 2 step 4) from the
`POST /api/v1/projects` response. Step 4a MUST preserve it — never overwrite the file from
scratch. The bash block below appends only the keys that are missing.

If `.cloglog/config.yaml` already exists, update fields rather than overwriting. When upgrading a project that predates T-316, append the four new keys (`dashboard_key`, `webhook_tunnel_name`, `reviewer_bot_logins`, `demo_allowlist_paths`) instead of regenerating the file from scratch.

#### 4a.1 — Append commented-out `worktree_scopes` template

After the scalar keys above are written, run this bash block to append a
*commented-out* `worktree_scopes` template if one isn't present. The block
is idempotent — if `worktree_scopes:` is already present (e.g. cloglog's
hand-written config), it's a no-op. `project_id` was seeded by Step 2 and
is left untouched.

**Why init emits a commented template, not an auto-detected mapping.** The
`protect-worktree-writes.sh` hook resolves a worktree's scope by stripping
`wt-` from the directory basename and looking up the remainder in this
map, with prefix matching (`wt-frontend-auth` matches scope `frontend`).
Live keys like `backend`/`frontend`/`mcp` would never match a normal
launched worktree such as `wt-t321-init-config-gen` — the lookup falls
through to the hook's allow-all branch and the guard becomes a silent
no-op. Until launch-time scope is wired through (a separate task), init's
job is to leave the operator a clear template to fill in once they've
chosen a naming convention for their launcher.

```bash
mkdir -p .cloglog
[ -f .cloglog/config.yaml ] || { echo "ERROR: .cloglog/config.yaml missing — Step 2 must run first"; exit 1; }

# Verify Step 2 seeded project_id. Without it, the MCP server has no
# canonical project identity and any consumer that reads project_id from
# config (e.g. scripts/sync_mcp_dist.py) silently breaks.
grep -q '^project_id:' .cloglog/config.yaml || {
  echo "ERROR: project_id missing from .cloglog/config.yaml — re-run Step 2 (Phase 2)"
  exit 1
}

if ! grep -q '^worktree_scopes:' .cloglog/config.yaml \
   && ! grep -q '^# worktree_scopes:' .cloglog/config.yaml; then
  cat >> .cloglog/config.yaml <<'YAML'

# worktree_scopes: <scope>: [<path-prefix>, ...] mapping consumed by the
# protect-worktree-writes hook. The hook strips `wt-` from the worktree
# basename and looks up the remainder here (with prefix matching:
# `wt-frontend-auth` -> `frontend`). Scope keys MUST match the
# worktree-naming convention used by your /cloglog launch flow — keys
# that don't match any worktree name leave the hook in allow-all mode.
# Uncomment and adapt after you've settled on a convention.
# worktree_scopes:
#   <scope>: [<path-prefix>/, ...]   # e.g. backend: [src/, tests/]
YAML
fi
```

### 4b. `on-worktree-create.sh`

Detect the tech stack and generate the appropriate setup script. The generated
script must contain **only generic dependency-fetch commands** for the
detected stack — never cloglog-specific machinery (see "Cloglog-specific
extensions" below).

**Python with uv** (detected by `pyproject.toml` + `uv.lock` or `[tool.uv]`):
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "${WORKTREE_PATH:?WORKTREE_PATH must be set}"
uv sync
```

**Python without uv** (detected by `pyproject.toml` or `requirements.txt`, no `uv.lock`):
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "${WORKTREE_PATH:?WORKTREE_PATH must be set}"
python3 -m venv .venv
. .venv/bin/activate
if [ -f pyproject.toml ]; then pip install -e .; fi
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
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

**Go** (detected by `go.mod`):
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "${WORKTREE_PATH:?WORKTREE_PATH must be set}"
go mod download
```

**Java / Maven** (detected by `pom.xml`):
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "${WORKTREE_PATH:?WORKTREE_PATH must be set}"
mvn -B dependency:go-offline
```

**Java / Gradle** (detected by `build.gradle` or `build.gradle.kts`):
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "${WORKTREE_PATH:?WORKTREE_PATH must be set}"
./gradlew --no-daemon dependencies
```

**Ruby / Bundler** (detected by `Gemfile`):
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "${WORKTREE_PATH:?WORKTREE_PATH must be set}"
bundle install
```

**Mixed** (multiple detected): combine the relevant commands in a single script.

**Unknown stack** (no recognised manifest): emit a stub with the same
`cd "${WORKTREE_PATH...}"` boilerplate as the other templates plus an
explanatory comment, so any commands the operator adds run inside the new
worktree (launch invokes `.cloglog/on-worktree-create.sh` by absolute path
and does NOT change cwd first — see `plugins/cloglog/skills/launch/SKILL.md`):
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "${WORKTREE_PATH:?WORKTREE_PATH must be set}"
# No tech stack auto-detected. Add project-specific worktree setup commands
# here (e.g., dependency install, codegen, schema sync). They run inside
# the new worktree (WORKTREE_PATH) because of the cd above.
```

Make the script executable: `chmod +x .cloglog/on-worktree-create.sh`

**Cloglog-specific extensions (do NOT emit from init).** The cloglog dogfood
project's hand-written `.cloglog/on-worktree-create.sh` performs additional
work that is **not** part of the generic init contract and must not be
generated for downstream projects:

- A `curl` POST to `/api/v1/agents/close-off-task` to seed a board task.
- A call to `${REPO_ROOT}/scripts/worktree-infra.sh` for per-worktree Postgres
  and port allocation.
- `shutdown-artifacts/` reset and other dogfood-only plumbing.

Downstream projects that need similar machinery opt in by editing their own
`on-worktree-create.sh` after init runs. Init's job is only the generic
dependency bootstrap above.

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
ORIGIN_URL=$(git remote get-url origin 2>/dev/null || true)
```

**If no remote exists** (`ORIGIN_URL` empty), the code hasn't been pushed to GitHub yet. Guide the user:

> **No GitHub remote found.** Before agents can create PRs, this project needs a GitHub repository.
>
> 1. Create a repo on GitHub (or use `gh repo create`)
> 2. Add the remote: `git remote add origin git@github.com:<owner>/<repo>.git`
> 3. Push: `git push -u origin main`
> 4. Run `/cloglog init` again to continue setup.

Record in the summary: `GitHub repo: not configured`. The init can continue for everything else — the bot check will be skipped.

**If a remote exists**, canonicalize the URL to the shape the backend's webhook router expects, then call `mcp__cloglog__update_project` to backfill the project's `repo_url`. The backend stores `repo_url` and the webhook consumer (`src/gateway/webhook_consumers.py`) and review engine (`src/gateway/review_engine.py`) match incoming events with `Project.repo_url.endswith(<repo_full_name>)`. A row carrying `git@github.com:owner/repo.git` (SSH) or `https://github.com/owner/repo.git` (with `.git`) would silently miss every webhook — so canonical bytes on disk are load-bearing.

```bash
# Canonicalize: strip whitespace, convert SSH → HTTPS, drop trailing .git
# and trailing slash. Mirrors src/board/repo_url.py::normalize_repo_url so
# init's pre-write shape matches what the backend stores.
CANONICAL_URL="$ORIGIN_URL"
CANONICAL_URL="${CANONICAL_URL#"${CANONICAL_URL%%[![:space:]]*}"}"  # ltrim
CANONICAL_URL="${CANONICAL_URL%"${CANONICAL_URL##*[![:space:]]}"}"  # rtrim
case "$CANONICAL_URL" in
  git@github.com:*) CANONICAL_URL="https://github.com/${CANONICAL_URL#git@github.com:}" ;;
  http://github.com/*) CANONICAL_URL="https://github.com/${CANONICAL_URL#http://github.com/}" ;;
esac
CANONICAL_URL="${CANONICAL_URL%.git}"
CANONICAL_URL="${CANONICAL_URL%/}"
echo "Canonical repo URL: $CANONICAL_URL"
```

Then ask the agent to call the MCP tool (the bash block above only computes the canonical URL — the MCP call goes through Claude's tool layer, not curl):

> Call `mcp__cloglog__update_project(repo_url="<CANONICAL_URL>")` to backfill the row.

The backend re-normalizes the URL on write, so re-running init on a project whose `repo_url` is already canonical is a no-op (same bytes in, same bytes stored). If the project was created by an earlier init that left `repo_url` empty, this call is the repair.

### 6b. Check if the GitHub App bot exists

Look for:
- `~/.agent-vm/credentials/github-app.pem` on disk (the only secret)
- `gh_app_id` and `gh_app_installation_id` resolvable for `gh-app-token.py`. Resolution order: env → `.cloglog/local.yaml` (gitignored, host-local — preferred for any clone) → `.cloglog/config.yaml` (tracked fallback)

**If the PEM exists** (bot has been set up before):

The token script `${CLAUDE_PLUGIN_ROOT}/scripts/gh-app-token.py` resolves
`GH_APP_ID` / `GH_APP_INSTALLATION_ID` (T-348) from: env → `.cloglog/local.yaml`
→ `.cloglog/config.yaml`. Add the two non-secret identifiers to
`.cloglog/local.yaml` (gitignored — App ID is visible on the App settings page;
Installation ID on the installation detail page):

```yaml
gh_app_id: "<your-app-id>"
gh_app_installation_id: "<your-installation-id>"
```

These values are **operator-host-specific** (each operator installs the App into
their own org/repo and gets a distinct Installation ID — committing them would
push other clones at the wrong installation). The PEM at
`~/.agent-vm/credentials/github-app.pem` remains the only secret.

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
> 3. Note the App ID and Installation ID — add `gh_app_id: "<id>"` and `gh_app_installation_id: "<id>"` to `.cloglog/local.yaml` (gitignored — T-348). `gh-app-token.py` reads them on every invocation; no shell RC export needed.
>
> Run `/cloglog init` again once the bot is set up.

Record in the summary: `GitHub bot: needs setup`. The init can continue — agents just won't be able to create PRs until this is done.

### 6c. Verify bot has access to THIS repo

Only run this if both the remote and the bot exist:

`gh-app-token.py` resolves `GH_APP_ID` / `GH_APP_INSTALLATION_ID` in this
order (T-348): process env → `.cloglog/local.yaml` (gitignored, preferred)
→ `.cloglog/config.yaml` (tracked fallback). Init verifies repo access by
running it directly — no env-priming required:

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests "${CLAUDE_PLUGIN_ROOT}/scripts/gh-app-token.py" 2>/dev/null)
if [[ -z "$BOT_TOKEN" ]]; then
  echo "WARNING: gh-app-token.py minted no token — check ~/.agent-vm/credentials/github-app.pem"
  echo "  and ensure gh_app_id / gh_app_installation_id are set in .cloglog/local.yaml."
else
  REPO=$(git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
  if GH_TOKEN="$BOT_TOKEN" gh repo view "$REPO" --json name -q .name 2>/dev/null; then
    echo "Bot has access to this repo"
  else
    echo "Bot does NOT have access to this repo"
  fi
fi
```

If the script exits non-zero (missing IDs, no PEM, or App not installed
on the repo), `BOT_TOKEN` will be empty and the WARNING fires — the access
check never silently no-ops on a misconfigured host.

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
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT must be set — re-run from a Claude Code session with the cloglog plugin installed}"
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

Add the runtime / host-local files to `.gitignore` so they never get
staged. `.cloglog/inbox` is runtime webhook state; `.cloglog/local.yaml`
holds operator-host-specific App identifiers (T-348) and committing it
would point other clones at the wrong GitHub App installation:

```bash
{ grep -qxF '.cloglog/inbox'      .gitignore 2>/dev/null || echo '.cloglog/inbox'      >> .gitignore; }
{ grep -qxF '.cloglog/local.yaml' .gitignore 2>/dev/null || echo '.cloglog/local.yaml' >> .gitignore; }
```

Then stage the tracked config files **explicitly** — never `git add
.cloglog/` as a directory, because that would pick up
`.cloglog/local.yaml` if the operator had already created it before
running this step:

```bash
git add .cloglog/config.yaml .gitignore
# Also add any tracked sibling files (varies per project — common ones below).
[[ -f .cloglog/on-worktree-create.sh ]]  && git add .cloglog/on-worktree-create.sh
[[ -f .cloglog/on-worktree-destroy.sh ]] && git add .cloglog/on-worktree-destroy.sh
[[ -d .github/codex ]] && git add .github/codex/
```

If CLAUDE.md/AGENTS.md was modified, add that too. Do not commit
automatically — let the user decide when to commit. Verify with
`git diff --cached --name-only` that `.cloglog/local.yaml` is NOT in
the staged changes before committing.

## Step 9: Summary

Present what was configured:

| Item | Value |
|------|-------|
| Project name | `<name>` |
| Quality command | `<command>` |
| Tech stack | Python/Node/Rust/Mixed |
| Config location | `.cloglog/config.yaml` |
| MCP configured | yes/no — `mcpServers.cloglog` written to `.mcp.json` |
| SessionStart hook | injected into `.claude/settings.json` |
| CLAUDE.md | updated/created |
| GitHub bot | configured/needs setup |

Remind the user to:
1. Set up the project's API key. On a single-project host, write `CLOGLOG_API_KEY=<key>` to `~/.cloglog/credentials` (chmod 600). On a multi-project host, write it to `~/.cloglog/credentials.d/<project_slug>` (chmod 600) so the legacy global file stays untouched for the other project — the T-382 resolver picks the per-project file automatically based on the `project:` field in `.cloglog/config.yaml`. `export CLOGLOG_API_KEY=<key>` works as a one-shot override and beats both file sources. See `${CLAUDE_PLUGIN_ROOT}/docs/setup-credentials.md`. The key MUST NOT live in `.mcp.json` (which now carries the `mcpServers.cloglog` entry) or `.claude/settings.json`.
2. **Set up the GitHub bot** if not yet configured (see Step 6 output)
3. Run `git commit` to save the configuration
4. Start the cloglog backend if not running

**If the GitHub bot is not configured**, warn prominently:
> **WARNING: GitHub bot is not configured.** Without it, agent PRs and pushes will use your personal GitHub identity. Follow the setup instructions above before launching agents.
