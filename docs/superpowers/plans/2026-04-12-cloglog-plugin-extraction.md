# Cloglog Plugin Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract cloglog's workflow discipline into a reusable Claude Code plugin at `plugins/cloglog/`, then make cloglog itself consume the plugin so nothing breaks.

**Architecture:** The plugin owns the agent orchestration workflow (worktree lifecycle, planning pipeline, PR discipline, zellij management). Projects provide tech-stack-specific configuration via `.cloglog/config.yaml` and optional hook scripts. State machine guards remain server-side in the cloglog backend.

**Tech Stack:** Claude Code plugin system (skills, hooks, agents, settings.json), Bash hooks, YAML config

---

## File Structure

### New files in `plugins/cloglog/`

```
plugins/cloglog/
├── package.json
├── skills/
│   ├── init/SKILL.md
│   ├── launch/SKILL.md
│   ├── close-wave/SKILL.md
│   ├── reconcile/SKILL.md
│   └── github-bot/SKILL.md
├── agents/
│   ├── worktree-agent.md
│   └── pr-postprocessor.md
├── hooks/
│   ├── worktree-create.sh
│   ├── worktree-remove.sh
│   ├── quality-gate.sh
│   ├── agent-shutdown.sh
│   ├── prefer-mcp.sh
│   ├── remind-pr-update.sh
│   ├── protect-worktree-writes.sh
│   ├── enforce-task-transitions.sh
│   └── block-sensitive-files.sh
├── settings.json
└── templates/
    └── claude-md-fragment.md
```

### New files in cloglog repo (project-specific config)

```
.cloglog/
├── config.yaml
├── on-worktree-create.sh
└── on-worktree-destroy.sh
```

### Files modified in cloglog repo

- `.claude/settings.json` — remove hooks that moved to plugin
- `CLAUDE.md` — split: generic workflow rules move to plugin template, project-specific stays

### Files deleted from cloglog repo

- `.claude/hooks/quality-gate-before-commit.sh` — replaced by plugin's `quality-gate.sh`
- `.claude/hooks/agent-shutdown.sh` — replaced by plugin's `agent-shutdown.sh`
- `.claude/hooks/prefer-mcp-over-api.sh` — replaced by plugin's `prefer-mcp.sh`
- `.claude/hooks/remind-pr-board-update.sh` — replaced by plugin's `remind-pr-update.sh`
- `.claude/hooks/protect-worktree-writes.sh` — replaced by plugin's `protect-worktree-writes.sh`
- `.claude/hooks/enforce-task-transitions.sh` — replaced by plugin's `enforce-task-transitions.sh`
- `.claude/hooks/block-sensitive-files.sh` — replaced by plugin's `block-sensitive-files.sh`
- `.claude/hooks/log-agent-spawn.sh` — dropped (optional telemetry, not core workflow)
- `.claude/commands/launch-worktree.md` — replaced by plugin's `launch` skill
- `.claude/commands/close-wave.md` — replaced by plugin's `close-wave` skill
- `.claude/skills/reconcile/` — replaced by plugin's `reconcile` skill
- `.claude/skills/github-bot/` — replaced by plugin's `github-bot` skill
- `.claude/agents/worktree-agent.md` — replaced by plugin's generic version
- `.claude/agents/pr-postprocessor.md` — replaced by plugin's generic version
- `scripts/create-worktree.sh` — replaced by native worktrees + WorktreeCreate hook
- `scripts/manage-worktrees.sh` — replaced by close-wave skill + WorktreeRemove hook
- `scripts/list-worktrees.sh` — replaced by reconcile skill

### Files that stay in cloglog (project-specific)

- `.claude/agents/ddd-architect.md`
- `.claude/agents/ddd-reviewer.md`
- `.claude/agents/test-writer.md`
- `.claude/agents/migration-validator.md`
- `.claude/skills/db-migration/`
- `scripts/worktree-ports.sh` — used by cloglog's `on-worktree-create.sh`
- `scripts/worktree-infra.sh` — used by cloglog's `on-worktree-create.sh`
- `scripts/gh-app-token.py` — bot token acquisition

---

## Task 1: Create plugin scaffold and package.json

**Files:**
- Create: `plugins/cloglog/package.json`

- [ ] **Step 1: Create the plugin directory**

```bash
mkdir -p plugins/cloglog/{skills/init,skills/launch,skills/close-wave,skills/reconcile,skills/github-bot,agents,hooks,templates}
```

- [ ] **Step 2: Write package.json**

```json
{
  "name": "cloglog",
  "version": "0.1.0",
  "description": "Agent orchestration workflow for cloglog-managed projects. Board-driven planning pipeline, worktree lifecycle, PR discipline, and multi-agent coordination.",
  "claude-code-plugin": true,
  "keywords": ["claude-code", "plugin", "workflow", "agents"]
}
```

- [ ] **Step 3: Commit**

```bash
git add plugins/cloglog/package.json
git commit -m "chore: scaffold cloglog plugin directory structure"
```

---

## Task 2: Extract and generalize hooks

All hooks need to read project config from `.cloglog/config.yaml` instead of hardcoding cloglog-specific values. Each hook must resolve the project root and config path dynamically.

**Files:**
- Create: `plugins/cloglog/hooks/quality-gate.sh`
- Create: `plugins/cloglog/hooks/agent-shutdown.sh`
- Create: `plugins/cloglog/hooks/prefer-mcp.sh`
- Create: `plugins/cloglog/hooks/remind-pr-update.sh`
- Create: `plugins/cloglog/hooks/protect-worktree-writes.sh`
- Create: `plugins/cloglog/hooks/enforce-task-transitions.sh`
- Create: `plugins/cloglog/hooks/block-sensitive-files.sh`
- Create: `plugins/cloglog/hooks/worktree-create.sh`
- Create: `plugins/cloglog/hooks/worktree-remove.sh`

### Step-by-step for each hook:

- [ ] **Step 1: Write `quality-gate.sh`**

Generalized version — reads quality command from `.cloglog/config.yaml` instead of hardcoding `make quality`. Keeps the Playwright e2e check only if the project has it.

```bash
#!/bin/bash
# Enforce quality gate before git commit/push/PR.
# Reads quality_command from .cloglog/config.yaml.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd')

[[ "$TOOL_NAME" == "Bash" ]] || exit 0
echo "$COMMAND" | grep -qE '(git commit|git push|gh pr create)' || exit 0

# Find project root (walk up to find .cloglog/config.yaml)
PROJECT_ROOT="$CWD"
while [[ "$PROJECT_ROOT" != "/" ]]; do
  [[ -f "$PROJECT_ROOT/.cloglog/config.yaml" ]] && break
  PROJECT_ROOT=$(dirname "$PROJECT_ROOT")
done
[[ -f "$PROJECT_ROOT/.cloglog/config.yaml" ]] || exit 0

# Read quality command from config
QUALITY_CMD=$(grep '^quality_command:' "$PROJECT_ROOT/.cloglog/config.yaml" | sed 's/^quality_command: *//')
[[ -n "$QUALITY_CMD" ]] || exit 0

cd "$PROJECT_ROOT" || exit 0

if ! eval "$QUALITY_CMD" > /tmp/quality-check-$$.log 2>&1; then
  echo "Blocked: quality gate failed ('$QUALITY_CMD'). Fix issues before committing." >&2
  echo "---" >&2
  tail -20 /tmp/quality-check-$$.log >&2
  rm -f /tmp/quality-check-$$.log
  exit 2
fi
rm -f /tmp/quality-check-$$.log
exit 0
```

- [ ] **Step 2: Write `agent-shutdown.sh`**

Generalized version — reads backend URL from config, works in any worktree path (not just `.claude/worktrees/`).

```bash
#!/bin/bash
# SessionEnd hook: generate shutdown artifacts and unregister worktree agents.
# Only runs if cwd is inside a git worktree (not the main working tree).

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd')

# Detect if we're in a git worktree (not the main working tree)
GIT_COMMON=$(cd "$CWD" && git rev-parse --git-common-dir 2>/dev/null)
GIT_DIR=$(cd "$CWD" && git rev-parse --git-dir 2>/dev/null)
[[ -n "$GIT_COMMON" && -n "$GIT_DIR" && "$GIT_COMMON" != "$GIT_DIR" ]] || exit 0

WORKTREE_NAME=$(basename "$CWD")
ARTIFACTS_DIR="${CWD}/shutdown-artifacts"
mkdir -p "$ARTIFACTS_DIR"

# Find project root (where .cloglog/config.yaml lives)
PROJECT_ROOT="$CWD"
while [[ "$PROJECT_ROOT" != "/" ]]; do
  [[ -f "$PROJECT_ROOT/.cloglog/config.yaml" ]] && break
  PROJECT_ROOT=$(dirname "$PROJECT_ROOT")
done

# Read backend URL from config
BACKEND_URL="http://localhost:8000"
if [[ -f "$PROJECT_ROOT/.cloglog/config.yaml" ]]; then
  URL=$(grep '^backend_url:' "$PROJECT_ROOT/.cloglog/config.yaml" | sed 's/^backend_url: *//')
  [[ -n "$URL" ]] && BACKEND_URL="$URL"
fi

# Resolve API key
API_KEY="${CLOGLOG_API_KEY:-}"
if [[ -z "$API_KEY" && -f "${CWD}/.env" ]]; then
  API_KEY=$(grep CLOGLOG_API_KEY "${CWD}/.env" 2>/dev/null | cut -d= -f2 || true)
fi
if [[ -z "$API_KEY" ]]; then
  REPO_ROOT=$(cd "$CWD" && git rev-parse --show-toplevel 2>/dev/null || true)
  if [[ -n "$REPO_ROOT" && -f "${REPO_ROOT}/.mcp.json" ]]; then
    API_KEY=$(python3 -c "
import json
d=json.load(open('${REPO_ROOT}/.mcp.json'))
print(d.get('mcpServers',{}).get('cloglog',{}).get('env',{}).get('CLOGLOG_API_KEY',''))
" 2>/dev/null || true)
  fi
fi

# Generate shutdown artifacts
{
  echo "# Work Log: ${WORKTREE_NAME}"
  echo ""
  echo "**Date:** $(date +%Y-%m-%d)"
  echo "**Worktree:** ${WORKTREE_NAME}"
  echo ""
  echo "## Commits"
  echo '```'
  cd "$CWD" && git log --oneline main..HEAD 2>/dev/null || echo "(no commits)"
  echo '```'
  echo ""
  echo "## Files Changed"
  echo '```'
  cd "$CWD" && git diff --name-only main..HEAD 2>/dev/null || echo "(none)"
  echo '```'
} > "${ARTIFACTS_DIR}/work-log.md"

{
  echo "# Learnings: ${WORKTREE_NAME}"
  echo ""
  echo "**Date:** $(date +%Y-%m-%d)"
  echo ""
  echo "## What Went Well"
  echo ""
  echo "<!-- Fill in during consolidation -->"
  echo ""
  echo "## Issues Encountered"
  echo ""
  echo "<!-- Fill in during consolidation -->"
  echo ""
  echo "## Suggestions for CLAUDE.md"
  echo ""
  echo "<!-- Fill in during consolidation -->"
} > "${ARTIFACTS_DIR}/learnings.md"

# Unregister agent
if [[ -n "$API_KEY" ]]; then
  curl -s --max-time 5 -X POST "${BACKEND_URL}/api/v1/agents/unregister-by-path" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    -d "{
      \"worktree_path\": \"${CWD}\",
      \"artifacts\": {
        \"work_log\": \"${ARTIFACTS_DIR}/work-log.md\",
        \"learnings\": \"${ARTIFACTS_DIR}/learnings.md\"
      }
    }" > /dev/null 2>&1 || true
fi

exit 0
```

- [ ] **Step 3: Write `prefer-mcp.sh`**

Generalized — reads backend URL from config instead of hardcoding `localhost:8000`.

```bash
#!/bin/bash
# Block direct curl/wget calls to the cloglog backend. Use MCP tools instead.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd')

[[ "$TOOL_NAME" == "Bash" ]] || exit 0
[[ -n "$COMMAND" ]] || exit 0

# Find backend URL from config
PROJECT_ROOT="$CWD"
while [[ "$PROJECT_ROOT" != "/" ]]; do
  [[ -f "$PROJECT_ROOT/.cloglog/config.yaml" ]] && break
  PROJECT_ROOT=$(dirname "$PROJECT_ROOT")
done

BACKEND_URL="localhost:8000"
if [[ -f "$PROJECT_ROOT/.cloglog/config.yaml" ]]; then
  URL=$(grep '^backend_url:' "$PROJECT_ROOT/.cloglog/config.yaml" | sed 's/^backend_url: *//' | sed 's|https\?://||')
  [[ -n "$URL" ]] && BACKEND_URL="$URL"
fi

if echo "$COMMAND" | grep -qE "curl.*${BACKEND_URL}/api|wget.*${BACKEND_URL}/api"; then
  if echo "$COMMAND" | grep -qiE 'test|debug|verify|check.*status'; then
    exit 0
  fi
  echo "Blocked: Use MCP tools (mcp__cloglog__*) instead of direct API calls." >&2
  exit 2
fi

exit 0
```

- [ ] **Step 4: Write `remind-pr-update.sh`**

This is already generic — no changes needed except copying.

```bash
#!/bin/bash
# PostToolUse:Bash — remind to update board when a PR is created.

INPUT=$(cat /dev/stdin 2>/dev/null || echo "{}")
TOOL_OUTPUT=$(echo "$INPUT" | jq -r '.tool_response // empty' 2>/dev/null)

PR_URL=$(echo "$TOOL_OUTPUT" | grep -oE 'https://github\.com/[^/]+/[^/]+/pull/[0-9]+' | head -1)

if [ -n "$PR_URL" ]; then
    echo "PR created: $PR_URL — update the board: call update_task_status to move the active task to review with this PR URL."
fi
```

- [ ] **Step 5: Write `protect-worktree-writes.sh`**

Generalized — reads scopes from `.cloglog/config.yaml` instead of hardcoded case statement. No-op if no scopes defined.

```bash
#!/bin/bash
# Enforce worktree directory restrictions if worktree_scopes defined in config.

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd')

# Detect if in a git worktree
GIT_COMMON=$(cd "$CWD" && git rev-parse --git-common-dir 2>/dev/null)
GIT_DIR=$(cd "$CWD" && git rev-parse --git-dir 2>/dev/null)
[[ -n "$GIT_COMMON" && -n "$GIT_DIR" && "$GIT_COMMON" != "$GIT_DIR" ]] || exit 0

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
[[ -n "$FILE_PATH" ]] || exit 0

WORKTREE_NAME=$(basename "$CWD")

# Find project root with config
PROJECT_ROOT="$CWD"
while [[ "$PROJECT_ROOT" != "/" ]]; do
  [[ -f "$PROJECT_ROOT/.cloglog/config.yaml" ]] && break
  PROJECT_ROOT=$(dirname "$PROJECT_ROOT")
done
# If we're in a worktree, project root might be the main repo
if [[ ! -f "$PROJECT_ROOT/.cloglog/config.yaml" ]]; then
  MAIN_ROOT=$(cd "$CWD" && git rev-parse --git-common-dir 2>/dev/null | sed 's|/\.git$||')
  [[ -f "$MAIN_ROOT/.cloglog/config.yaml" ]] && PROJECT_ROOT="$MAIN_ROOT"
fi
[[ -f "$PROJECT_ROOT/.cloglog/config.yaml" ]] || exit 0

# Check if worktree_scopes is defined and has an entry for this worktree
# Config format:
# worktree_scopes:
#   board: [src/board/, tests/board/, src/alembic/]
#   frontend: [frontend/]
SCOPE_KEY=$(echo "$WORKTREE_NAME" | sed 's/^wt-//')
# Try exact match first, then prefix match
ALLOWED=$(python3 -c "
import yaml, sys
try:
    cfg = yaml.safe_load(open('$PROJECT_ROOT/.cloglog/config.yaml'))
    scopes = cfg.get('worktree_scopes') or {}
    key = '$SCOPE_KEY'
    # Exact match
    if key in scopes:
        print(' '.join(scopes[key]))
        sys.exit(0)
    # Prefix match (e.g. 'frontend-auth' matches 'frontend')
    for k, v in scopes.items():
        if key.startswith(k):
            print(' '.join(v))
            sys.exit(0)
    # No match — no restriction
    sys.exit(0)
except Exception:
    sys.exit(0)
" 2>/dev/null)

# No scopes for this worktree — allow all writes
[[ -n "$ALLOWED" ]] || exit 0

REL_PATH="${FILE_PATH#$CWD/}"
# Also try relative to project root for paths outside worktree dir
[[ "$REL_PATH" == "$FILE_PATH" ]] && REL_PATH="${FILE_PATH#$PROJECT_ROOT/}"

for pattern in $ALLOWED; do
  [[ "$REL_PATH" == $pattern* ]] && exit 0
done

echo "Blocked: Worktree '$WORKTREE_NAME' can only write to: $ALLOWED" >&2
echo "Attempted write to: $REL_PATH" >&2
exit 2
```

- [ ] **Step 6: Write `enforce-task-transitions.sh`**

Generalized — reads backend URL and project ID from config instead of hardcoding.

```bash
#!/bin/bash
# Validate task state machine: done requires review first.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')

case "$TOOL_NAME" in
  mcp__cloglog__update_task_status) ;;
  mcp__cloglog__complete_task) ;;
  *) exit 0 ;;
esac

TARGET_STATUS=$(echo "$INPUT" | jq -r '.tool_input.status // empty')
TASK_ID=$(echo "$INPUT" | jq -r '.tool_input.task_id // empty')
[[ -n "$TASK_ID" ]] || exit 0

[[ "$TOOL_NAME" == "mcp__cloglog__complete_task" ]] && TARGET_STATUS="done"
[[ "$TARGET_STATUS" == "done" ]] || exit 0

CWD=$(echo "$INPUT" | jq -r '.cwd')

# Find config
PROJECT_ROOT="$CWD"
while [[ "$PROJECT_ROOT" != "/" ]]; do
  [[ -f "$PROJECT_ROOT/.cloglog/config.yaml" ]] && break
  PROJECT_ROOT=$(dirname "$PROJECT_ROOT")
done

BACKEND_URL="http://localhost:8000"
if [[ -f "$PROJECT_ROOT/.cloglog/config.yaml" ]]; then
  URL=$(grep '^backend_url:' "$PROJECT_ROOT/.cloglog/config.yaml" | sed 's/^backend_url: *//')
  [[ -n "$URL" ]] && BACKEND_URL="$URL"
fi

# We need the project ID to query the board. Read from config.
PROJECT_ID=$(grep '^project_id:' "$PROJECT_ROOT/.cloglog/config.yaml" 2>/dev/null | sed 's/^project_id: *//')
[[ -n "$PROJECT_ID" ]] || exit 0

BOARD_JSON=$(curl -s "${BACKEND_URL}/api/v1/projects/${PROJECT_ID}/board" 2>/dev/null)
[[ -n "$BOARD_JSON" ]] || { echo "Blocked: Backend unreachable — cannot verify task status." >&2; exit 2; }

CURRENT_STATUS=$(echo "$BOARD_JSON" | jq -r --arg tid "$TASK_ID" '
  .columns[].tasks[] | select(.id == $tid) | .status
' 2>/dev/null)

[[ -z "$CURRENT_STATUS" ]] && exit 0  # Task not found — allow (different project)

if [[ "$CURRENT_STATUS" != "review" ]]; then
  echo "Blocked: Cannot move task to 'done' — current status is '$CURRENT_STATUS', must be 'review' first." >&2
  exit 2
fi

exit 0
```

- [ ] **Step 7: Write `block-sensitive-files.sh`**

Already generic — copy as-is.

```bash
#!/bin/bash
# Block edits to .env files, credentials, secrets, and .mcp.json.

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.content // empty' 2>/dev/null)
[[ -z "$FILE_PATH" ]] && exit 0

BASENAME=$(basename "$FILE_PATH")

case "$BASENAME" in
  .env|.env.local|.env.production|.env.development)
    echo "Blocked: do not edit $BASENAME — contains port assignments and API keys"
    exit 2
    ;;
esac

if echo "$FILE_PATH" | grep -qiE 'credentials|secrets|\.mcp\.json'; then
  echo "Blocked: do not edit $BASENAME — contains sensitive configuration"
  exit 2
fi

exit 0
```

- [ ] **Step 8: Write `worktree-create.sh`**

New hook — fires on Claude Code's WorktreeCreate event. Registers agent and runs project setup.

```bash
#!/bin/bash
# WorktreeCreate hook: register agent on board, run project-specific setup.

INPUT=$(cat)
WORKTREE_PATH=$(echo "$INPUT" | jq -r '.worktree_path // empty')
[[ -n "$WORKTREE_PATH" ]] || exit 0

# Find project root
PROJECT_ROOT="$WORKTREE_PATH"
while [[ "$PROJECT_ROOT" != "/" ]]; do
  [[ -f "$PROJECT_ROOT/.cloglog/config.yaml" ]] && break
  PROJECT_ROOT=$(dirname "$PROJECT_ROOT")
done
# Worktrees live outside project root — try main repo
if [[ ! -f "$PROJECT_ROOT/.cloglog/config.yaml" ]]; then
  MAIN_ROOT=$(cd "$WORKTREE_PATH" && git rev-parse --git-common-dir 2>/dev/null | sed 's|/\.git$||')
  [[ -f "$MAIN_ROOT/.cloglog/config.yaml" ]] && PROJECT_ROOT="$MAIN_ROOT"
fi
[[ -f "$PROJECT_ROOT/.cloglog/config.yaml" ]] || exit 0

# Read config
BACKEND_URL=$(grep '^backend_url:' "$PROJECT_ROOT/.cloglog/config.yaml" | sed 's/^backend_url: *//')
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"

# Resolve API key
API_KEY="${CLOGLOG_API_KEY:-}"
if [[ -z "$API_KEY" && -f "$PROJECT_ROOT/.mcp.json" ]]; then
  API_KEY=$(python3 -c "
import json
d=json.load(open('$PROJECT_ROOT/.mcp.json'))
print(d.get('mcpServers',{}).get('cloglog',{}).get('env',{}).get('CLOGLOG_API_KEY',''))
" 2>/dev/null || true)
fi

WORKTREE_NAME=$(basename "$WORKTREE_PATH")

# Register agent on board
if [[ -n "$API_KEY" ]]; then
  curl -s --max-time 5 -X POST "${BACKEND_URL}/api/v1/agents/register" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    -d "{
      \"worktree_name\": \"${WORKTREE_NAME}\",
      \"worktree_path\": \"${WORKTREE_PATH}\"
    }" > /dev/null 2>&1 || true
fi

# Run project-specific setup if it exists
if [[ -x "$PROJECT_ROOT/.cloglog/on-worktree-create.sh" ]]; then
  WORKTREE_PATH="$WORKTREE_PATH" WORKTREE_NAME="$WORKTREE_NAME" \
    "$PROJECT_ROOT/.cloglog/on-worktree-create.sh"
fi

exit 0
```

- [ ] **Step 9: Write `worktree-remove.sh`**

New hook — fires on Claude Code's WorktreeRemove event.

```bash
#!/bin/bash
# WorktreeRemove hook: run project-specific cleanup, close zellij tab.

INPUT=$(cat)
WORKTREE_PATH=$(echo "$INPUT" | jq -r '.worktree_path // empty')
[[ -n "$WORKTREE_PATH" ]] || exit 0

WORKTREE_NAME=$(basename "$WORKTREE_PATH")

# Find project root
PROJECT_ROOT="$WORKTREE_PATH"
while [[ "$PROJECT_ROOT" != "/" ]]; do
  [[ -f "$PROJECT_ROOT/.cloglog/config.yaml" ]] && break
  PROJECT_ROOT=$(dirname "$PROJECT_ROOT")
done
if [[ ! -f "$PROJECT_ROOT/.cloglog/config.yaml" ]]; then
  MAIN_ROOT=$(cd "$WORKTREE_PATH" 2>/dev/null && git rev-parse --git-common-dir 2>/dev/null | sed 's|/\.git$||')
  [[ -f "$MAIN_ROOT/.cloglog/config.yaml" ]] && PROJECT_ROOT="$MAIN_ROOT"
fi

# Run project-specific cleanup if it exists
if [[ -x "$PROJECT_ROOT/.cloglog/on-worktree-destroy.sh" ]]; then
  WORKTREE_PATH="$WORKTREE_PATH" WORKTREE_NAME="$WORKTREE_NAME" \
    "$PROJECT_ROOT/.cloglog/on-worktree-destroy.sh"
fi

# Close zellij tab if running in zellij
if [[ -n "$ZELLIJ" ]]; then
  TAB_ID=$(zellij action list-tabs 2>/dev/null | awk -v name="$WORKTREE_NAME" '$3 == name {print $1}')
  if [[ -n "$TAB_ID" ]]; then
    zellij action close-tab --tab-id "$TAB_ID" 2>/dev/null || true
  fi
fi

exit 0
```

- [ ] **Step 10: Make all hooks executable and commit**

```bash
chmod +x plugins/cloglog/hooks/*.sh
git add plugins/cloglog/hooks/
git commit -m "feat(plugin): extract and generalize all hooks from cloglog"
```

---

## Task 3: Write plugin settings.json

**Files:**
- Create: `plugins/cloglog/settings.json`

- [ ] **Step 1: Write settings.json registering all hooks**

```json
{
  "hooks": {
    "WorktreeCreate": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$PLUGIN_DIR/hooks/worktree-create.sh",
            "timeout": 15
          }
        ]
      }
    ],
    "WorktreeRemove": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$PLUGIN_DIR/hooks/worktree-remove.sh",
            "timeout": 15
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "$PLUGIN_DIR/hooks/agent-shutdown.sh",
            "timeout": 30
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "$PLUGIN_DIR/hooks/protect-worktree-writes.sh",
            "timeout": 5
          },
          {
            "type": "command",
            "command": "$PLUGIN_DIR/hooks/block-sensitive-files.sh",
            "timeout": 5
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "$PLUGIN_DIR/hooks/quality-gate.sh",
            "timeout": 120
          },
          {
            "type": "command",
            "command": "$PLUGIN_DIR/hooks/prefer-mcp.sh",
            "timeout": 5
          }
        ]
      },
      {
        "matcher": "mcp__cloglog__update_task_status|mcp__cloglog__complete_task",
        "hooks": [
          {
            "type": "command",
            "command": "$PLUGIN_DIR/hooks/enforce-task-transitions.sh",
            "timeout": 10
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "$PLUGIN_DIR/hooks/remind-pr-update.sh",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

Note: `$PLUGIN_DIR` must be verified as the correct environment variable that Claude Code exposes for plugin-relative paths. If Claude Code uses a different mechanism (e.g. paths relative to the plugin's `settings.json`), adjust accordingly. Check Claude Code plugin documentation before implementing.

- [ ] **Step 2: Commit**

```bash
git add plugins/cloglog/settings.json
git commit -m "feat(plugin): register all hooks in plugin settings.json"
```

---

## Task 4: Extract and generalize skills

**Files:**
- Create: `plugins/cloglog/skills/github-bot/SKILL.md`
- Create: `plugins/cloglog/skills/reconcile/SKILL.md`
- Create: `plugins/cloglog/skills/launch/SKILL.md`
- Create: `plugins/cloglog/skills/close-wave/SKILL.md`
- Create: `plugins/cloglog/skills/init/SKILL.md`

- [ ] **Step 1: Write `github-bot/SKILL.md`**

Extract from `.claude/skills/github-bot/SKILL.md`. The skill is already mostly generic. Changes:
- Remove hardcoded `sachinkundu/cloglog` repo references — use `$(gh repo view --json nameWithOwner -q .nameWithOwner)` or `git remote get-url origin`
- Keep the bot token acquisition via `scripts/gh-app-token.py` but document it as configurable
- Keep all the PR workflow patterns (polling, comment checking, CI recovery)

The skill content should include:
- Getting a bot token (currently `uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py`)
- Push + create PR pattern
- PR status checking (all 5 sources: merge state, CI, inline comments, issue comments, reviews)
- PR polling loop setup
- Reply to review comments
- CI failure recovery
- Rules: every `gh` needs `GH_TOKEN`, fresh token per batch, board update atomic with PR creation

Replace all `sachinkundu/cloglog` with dynamic repo detection:
```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
```

- [ ] **Step 2: Write `reconcile/SKILL.md`**

Extract from `.claude/skills/reconcile/SKILL.md`. Changes:
- Remove hardcoded project references
- Use project from `.cloglog/config.yaml`
- Keep all 5 checks (tasks vs PR, agents vs tasks, worktrees vs branches, stale branches, orphaned PRs)
- Keep auto-fix behavior
- Remove `./scripts/manage-worktrees.sh` references — use `git worktree remove` directly + project's on-worktree-destroy.sh

- [ ] **Step 3: Write `launch/SKILL.md`**

Extract from `.claude/commands/launch-worktree.md`. Major changes:
- Remove DDD contract flow (architect/reviewer routing) — that's project-specific
- Remove `create-worktree.sh` call — use Claude Code native `isolation: "worktree"` on Agent tool
- Remove cloglog-specific worktree name mappings
- Keep: git status pre-check, task resolution, prompt assembly, zellij tab creation, verification
- The skill assembles the agent prompt with: task details (from board MCP), workflow rules, project CLAUDE.md path
- Agent prompt template should include: task IDs, feature context, instruction to read project CLAUDE.md, workflow pipeline steps

- [ ] **Step 4: Write `close-wave/SKILL.md`**

Extract from `.claude/commands/close-wave.md`. Changes:
- Remove `manage-worktrees.sh` calls — use `git worktree remove` + project hooks
- Remove cloglog-specific integration verification (route registration, auth consistency, Alembic checks)
- Keep: PR merge verification, work log generation, zellij tab closing, remote branch cleanup, quality gate on main
- Add: spawn pr-postprocessor agent for learnings extraction

- [ ] **Step 5: Write `init/SKILL.md`**

New skill. Content:
- Detect project name from directory
- Ask quality gate command (try to detect from Makefile)
- Register project on board via MCP (`mcp__cloglog__create_project` or equivalent endpoint — verify this exists)
- Configure MCP server in `.claude/settings.json`
- Generate `.cloglog/config.yaml`
- Detect tech stack and generate `on-worktree-create.sh`:
  - `pyproject.toml` with `[tool.uv]` → `cd "$WORKTREE_PATH" && uv sync`
  - `package.json` → `cd "$WORKTREE_PATH" && npm install`
  - `Cargo.toml` → `cd "$WORKTREE_PATH" && cargo build`
  - None detected → no script
- Inject workflow fragment from `templates/claude-md-fragment.md` into CLAUDE.md
- Idempotent — re-running updates without duplicating

- [ ] **Step 6: Commit all skills**

```bash
git add plugins/cloglog/skills/
git commit -m "feat(plugin): extract and generalize all skills"
```

---

## Task 5: Extract and generalize agents

**Files:**
- Create: `plugins/cloglog/agents/worktree-agent.md`
- Create: `plugins/cloglog/agents/pr-postprocessor.md`

- [ ] **Step 1: Write generic `worktree-agent.md`**

Extract from `.claude/agents/worktree-agent.md`. Changes:
- Remove all cloglog-specific references (DDD, bounded contexts, contract checking)
- Remove hardcoded subagent types (ddd-architect, migration-validator) — the agent reads project CLAUDE.md for which subagents to use
- Keep: pipeline lifecycle (get tasks, spec/plan/impl flow, shutdown), PR discipline, MCP tool usage, polling loop, subagent-driven development for impl, test-writer spawning pattern, code-reviewer spawning pattern
- Add: instruction to read project CLAUDE.md for project-specific methodology and subagent configuration
- Keep model: sonnet

Key sections:
1. First steps: read project CLAUDE.md, get assigned tasks via MCP
2. Pipeline flow: spec (PR + artifact) -> plan (commit, no PR) -> impl (PR)
3. PR workflow: bot identity, quality gate, test report, demo
4. Subagent spawning: test-writer and code-reviewer are mentioned as patterns, but project CLAUDE.md may specify additional agents
5. Shutdown: artifacts + unregister when get_my_tasks returns empty

- [ ] **Step 2: Write generic `pr-postprocessor.md`**

Extract from `.claude/agents/pr-postprocessor.md`. Changes:
- Remove `./scripts/manage-worktrees.sh remove` call — use `git worktree remove` directly
- Remove cloglog-specific consolidation paths
- Keep: read PR diff, extract learnings, update CLAUDE.md, consolidate work logs
- Keep model: sonnet

- [ ] **Step 3: Commit agents**

```bash
git add plugins/cloglog/agents/
git commit -m "feat(plugin): extract generic worktree-agent and pr-postprocessor"
```

---

## Task 6: Write the CLAUDE.md workflow fragment template

**Files:**
- Create: `plugins/cloglog/templates/claude-md-fragment.md`

- [ ] **Step 1: Extract generic workflow rules from cloglog's CLAUDE.md**

The template contains the agent learnings and workflow rules that apply to ANY project. It's injected into a project's CLAUDE.md by the `init` skill.

Content to include (from cloglog's CLAUDE.md "Agent Learnings" section, generalized):
- Testing discipline (run tests first, every PR includes tests)
- PR quality (body structure: summary, demo, test report)
- Proof-of-work demos
- Execution workflow (spec -> plan -> impl pipeline)
- Agent shutdown protocol
- Feature pipeline continuity (create all 3 tasks, complete full pipeline)
- Worktree hygiene (commit before creating worktrees)
- PR polling and CI recovery
- Agent communication (inbox files, Monitor)

Content to EXCLUDE (cloglog-specific):
- DDD references
- Pydantic schema gotcha
- Alembic migration notes
- Route registration
- Contract enforcement
- Bounded context mappings

- [ ] **Step 2: Commit template**

```bash
git add plugins/cloglog/templates/
git commit -m "feat(plugin): add CLAUDE.md workflow fragment template"
```

---

## Task 7: Create cloglog's project-specific config

**Files:**
- Create: `.cloglog/config.yaml`
- Create: `.cloglog/on-worktree-create.sh`
- Create: `.cloglog/on-worktree-destroy.sh`

- [ ] **Step 1: Write `.cloglog/config.yaml`**

```yaml
project: cloglog
project_id: 4d9e825a-c911-4110-bcd5-9072d1887813
backend_url: http://localhost:8000
quality_command: make quality

worktree_scopes:
  board: [src/board/, tests/board/, src/alembic/]
  agent: [src/agent/, tests/agent/, src/alembic/]
  document: [src/document/, tests/document/, src/alembic/]
  gateway: [src/gateway/, tests/gateway/, src/shared/]
  frontend: [frontend/]
  mcp: [mcp-server/]
  assign: [src/gateway/, src/board/, tests/gateway/, tests/board/]
  e2e: [tests/e2e/]
```

- [ ] **Step 2: Write `.cloglog/on-worktree-create.sh`**

This extracts the infrastructure setup from `scripts/create-worktree.sh` — ports, DB, deps.

```bash
#!/bin/bash
# Project-specific worktree setup for cloglog.
# Called by the cloglog plugin's WorktreeCreate hook.
# Env: WORKTREE_PATH, WORKTREE_NAME

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)/scripts"

# Source port assignments
WORKTREE_NAME="${WORKTREE_NAME}" source "${SCRIPT_DIR}/worktree-ports.sh"

# Set up isolated infrastructure (database, migrations, .env)
"${SCRIPT_DIR}/worktree-infra.sh" up "$WORKTREE_NAME" "$WORKTREE_PATH"

# Install dependencies
cd "$WORKTREE_PATH"

# Python deps
if [[ -f "pyproject.toml" ]]; then
  uv sync 2>/dev/null || true
fi

# Frontend deps (if worktree touches frontend)
if [[ "$WORKTREE_NAME" == wt-frontend* ]] && [[ -d "frontend" ]]; then
  cd frontend && npm install && cd ..
fi

# MCP server deps (if worktree touches mcp-server)
if [[ "$WORKTREE_NAME" == wt-mcp* ]] && [[ -d "mcp-server" ]]; then
  cd mcp-server && npm install && cd ..
fi

echo "Worktree $WORKTREE_NAME infrastructure ready."
echo "  Backend: http://localhost:${BACKEND_PORT}"
echo "  Frontend: http://localhost:${FRONTEND_PORT}"
echo "  Database: ${WORKTREE_DB_NAME}"
```

- [ ] **Step 3: Write `.cloglog/on-worktree-destroy.sh`**

Extracts infrastructure teardown.

```bash
#!/bin/bash
# Project-specific worktree cleanup for cloglog.
# Called by the cloglog plugin's WorktreeRemove hook.
# Env: WORKTREE_PATH, WORKTREE_NAME

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)/scripts"

# Tear down isolated infrastructure (kill ports, drop DB)
"${SCRIPT_DIR}/worktree-infra.sh" down "$WORKTREE_NAME" "$WORKTREE_PATH" 2>/dev/null || true

echo "Worktree $WORKTREE_NAME infrastructure cleaned up."
```

- [ ] **Step 4: Make scripts executable and commit**

```bash
chmod +x .cloglog/on-worktree-create.sh .cloglog/on-worktree-destroy.sh
git add .cloglog/
git commit -m "feat: add cloglog project-specific config and worktree hooks"
```

---

## Task 8: Update cloglog's .claude/settings.json

Remove hooks that moved to the plugin. Keep only project-specific entries (if any remain).

**Files:**
- Modify: `.claude/settings.json`

- [ ] **Step 1: Read current settings.json**

Read `.claude/settings.json` to confirm current state.

- [ ] **Step 2: Replace settings.json content**

Since ALL hooks moved to the plugin, the project's settings.json should be minimal — only project-specific hook overrides if any. The plugin's settings.json handles everything.

However, we need to verify: does Claude Code merge plugin settings.json with project settings.json? Or does one override the other? Check Claude Code plugin documentation for how `settings.json` in plugins interacts with the project's `.claude/settings.json`.

If they merge, write an empty hooks section:
```json
{
}
```

If the project settings override plugin settings, we may need to keep the project settings pointing to the plugin hooks. Investigate before writing.

- [ ] **Step 3: Commit**

```bash
git add .claude/settings.json
git commit -m "refactor: remove hooks that moved to cloglog plugin"
```

---

## Task 9: Split cloglog's CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Read current CLAUDE.md**

Read the full file to understand what stays vs moves.

- [ ] **Step 2: Remove generic workflow rules that are now in the plugin template**

Remove from CLAUDE.md:
- The generic parts of "Agent Learnings" that are now in `templates/claude-md-fragment.md`
- Generic workflow instructions that the plugin provides

Keep in CLAUDE.md:
- Project Overview
- Architecture (DDD bounded contexts)
- Worktree Discipline (the DDD-specific part — the generic enforcement is in the plugin)
- Commands (`make quality`, etc.)
- Environment Quirks
- Quality Gate
- Git Identity & PRs
- Non-Negotiable Principles
- Tech Stack
- DDD-specific agent learnings (Pydantic schema, Alembic migrations, route registration, contract enforcement, etc.)

Add to CLAUDE.md:
- A note that this project uses the cloglog plugin for workflow discipline
- Project-specific agent instructions (e.g., "For spec tasks, spawn ddd-architect and ddd-reviewer agents")

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "refactor: split CLAUDE.md — generic workflow rules moved to plugin"
```

---

## Task 10: Remove replaced files

**Files:**
- Delete: `.claude/hooks/quality-gate-before-commit.sh`
- Delete: `.claude/hooks/agent-shutdown.sh`
- Delete: `.claude/hooks/prefer-mcp-over-api.sh`
- Delete: `.claude/hooks/remind-pr-board-update.sh`
- Delete: `.claude/hooks/protect-worktree-writes.sh`
- Delete: `.claude/hooks/enforce-task-transitions.sh`
- Delete: `.claude/hooks/block-sensitive-files.sh`
- Delete: `.claude/hooks/log-agent-spawn.sh`
- Delete: `.claude/commands/launch-worktree.md`
- Delete: `.claude/commands/close-wave.md`
- Delete: `.claude/skills/reconcile/SKILL.md`
- Delete: `.claude/skills/github-bot/SKILL.md`
- Delete: `.claude/agents/worktree-agent.md`
- Delete: `.claude/agents/pr-postprocessor.md`
- Delete: `scripts/create-worktree.sh`
- Delete: `scripts/manage-worktrees.sh`
- Delete: `scripts/list-worktrees.sh`

- [ ] **Step 1: Remove all files that moved to the plugin**

```bash
rm -f .claude/hooks/quality-gate-before-commit.sh
rm -f .claude/hooks/agent-shutdown.sh
rm -f .claude/hooks/prefer-mcp-over-api.sh
rm -f .claude/hooks/remind-pr-board-update.sh
rm -f .claude/hooks/protect-worktree-writes.sh
rm -f .claude/hooks/enforce-task-transitions.sh
rm -f .claude/hooks/block-sensitive-files.sh
rm -f .claude/hooks/log-agent-spawn.sh
rm -f .claude/commands/launch-worktree.md
rm -f .claude/commands/close-wave.md
rm -rf .claude/skills/reconcile/
rm -rf .claude/skills/github-bot/
rm -f .claude/agents/worktree-agent.md
rm -f .claude/agents/pr-postprocessor.md
rm -f scripts/create-worktree.sh
rm -f scripts/manage-worktrees.sh
rm -f scripts/list-worktrees.sh
```

- [ ] **Step 2: Verify no dangling references**

```bash
# Check for references to deleted files
grep -r "create-worktree.sh\|manage-worktrees.sh\|list-worktrees.sh" . --include="*.md" --include="*.sh" --include="*.json" | grep -v "plugins/cloglog" | grep -v ".git/"
grep -r "launch-worktree\|close-wave" .claude/ --include="*.json" | grep -v "plugins/"
```

Fix any dangling references found.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: remove files replaced by cloglog plugin"
```

---

## Task 11: Verify plugin installation and hook registration

**Files:** None (verification only)

- [ ] **Step 1: Check plugin is discoverable**

Verify Claude Code can see the plugin. The exact mechanism depends on how local plugins are installed — may need `claude plugins install ./plugins/cloglog` or a symlink.

```bash
# Check if Claude Code has a local plugin install mechanism
claude plugins list
```

- [ ] **Step 2: Verify hooks fire correctly**

Start a new Claude session in the cloglog repo and test:

1. **Quality gate hook**: Try `git commit --allow-empty -m "test"` — should trigger quality gate
2. **Block sensitive files hook**: Try to edit `.env` — should be blocked
3. **Prefer MCP hook**: Try `curl localhost:8000/api/...` — should be blocked
4. **Worktree write protection**: Create a test worktree, try writing outside scopes — should be blocked

- [ ] **Step 3: Verify WorktreeCreate hook**

Test native worktree creation:
```bash
# In a Claude session, use Agent with isolation: "worktree"
# The WorktreeCreate hook should fire, registering the agent on the board
# Check the board to verify registration
```

- [ ] **Step 4: Document any issues and fix**

If hooks don't fire or paths are wrong, fix the plugin's settings.json or hook scripts.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix(plugin): hook registration fixes from verification testing"
```

---

## Task 12: End-to-end workflow test

**Files:** None (testing only)

- [ ] **Step 1: Create a test feature on the board**

```
# Via MCP tools:
create_feature(epic_id, "Test plugin extraction — verify full workflow")
```

- [ ] **Step 2: Launch a worktree agent for the test feature**

Use the plugin's launch skill:
```
/cloglog launch F-<test-feature-id>
```

Verify:
- Worktree is created via Claude Code native mechanism
- WorktreeCreate hook fires and registers agent on board
- `.cloglog/on-worktree-create.sh` runs (ports, DB, deps)
- Zellij tab is created with correct name
- Agent starts and picks up tasks

- [ ] **Step 3: Verify agent follows pipeline**

Watch the agent through:
- Spec task: writes spec, creates PR, moves to review
- Plan task: writes plan, commits, proceeds
- Impl task: implements, creates PR, moves to review

- [ ] **Step 4: Test close-wave**

After the test feature's PRs are merged (or use a mock):
```
/cloglog close-wave
```

Verify:
- PR merge verification works
- Work log generated
- Zellij tab closed
- Worktree removed
- WorktreeRemove hook fires
- `.cloglog/on-worktree-destroy.sh` runs (infra teardown)
- Quality gate passes on main

- [ ] **Step 5: Test reconcile**

```
/reconcile
```

Verify:
- All 5 checks run correctly
- Auto-fix works for any detected drift
- Uses project config for backend URL

- [ ] **Step 6: Clean up test feature**

Remove the test feature from the board.

- [ ] **Step 7: Document results and commit any remaining fixes**

```bash
git add -A
git commit -m "test: verify full workflow after plugin extraction"
```

---

## Task 13: Update references in documentation

**Files:**
- Modify: `docs/zellij-guide.md` — update references to old scripts
- Modify: `Makefile` — remove targets that referenced deleted scripts (if any)
- Modify: any other docs referencing `create-worktree.sh` or `manage-worktrees.sh`

- [ ] **Step 1: Find all references to deleted files**

```bash
grep -rn "create-worktree\|manage-worktrees\|list-worktrees" docs/ Makefile README.md 2>/dev/null
```

- [ ] **Step 2: Update references to point to plugin skills**

Replace script references with plugin skill references (e.g., "use `/cloglog launch` instead of `create-worktree.sh`").

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "docs: update references from old scripts to cloglog plugin skills"
```
