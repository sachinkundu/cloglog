#!/bin/bash
# SessionEnd hook: generates shutdown artifacts and unregisters worktree agents.
# Detects worktree via git (comparing --git-common-dir vs --git-dir).
# Reads backend_url from .cloglog/config.yaml.

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd')

# T-217: write an unconditional breadcrumb as the very first step so that
# post-incident investigators can tell whether Claude ran SessionEnd at all,
# even if a subsequent step errors out. Presence of this file answers the
# "did the hook fire?" question; absence means Claude never ran it.
{
  echo "[$(date -Iseconds)] agent-shutdown.sh fired"
  echo "  cwd=${CWD}"
  echo "  tool_input_keys=$(echo "$INPUT" | jq -r 'keys | join(",")' 2>/dev/null || echo '?')"
} >> /tmp/agent-shutdown-debug.log 2>&1 || true

# --- Detect if we're in a worktree ---
GIT_DIR=$(cd "$CWD" && git rev-parse --git-dir 2>/dev/null) || exit 0
GIT_COMMON=$(cd "$CWD" && git rev-parse --git-common-dir 2>/dev/null) || exit 0

# Normalize to absolute paths for comparison
GIT_DIR=$(cd "$CWD" && cd "$GIT_DIR" && pwd)
GIT_COMMON=$(cd "$CWD" && cd "$GIT_COMMON" && pwd)

# If git-dir == git-common-dir, this is the main repo, not a worktree
if [[ "$GIT_DIR" == "$GIT_COMMON" ]]; then
  # Resolve the repo root so cleanup targets the canonical
  # `.cloglog/` directory even if the SessionEnd-reported `cwd` is a
  # nested subdir (codex review on PR #287 round 4).
  MAIN_ROOT=$(cd "$CWD" && git rev-parse --show-toplevel 2>/dev/null) || MAIN_ROOT="$CWD"
  # Main agent: clear the inbox on exit so next session starts clean
  INBOX="${MAIN_ROOT}/.cloglog/inbox"
  if [[ -f "$INBOX" ]]; then
    > "$INBOX"
  fi
  # T-371 codex review round 5: the supervisor's main-session
  # `register_agent` writes `<repo_root>/.cloglog/state.json` too
  # (setup SKILL §1). Without an rm here, ending a main-agent
  # session and reopening before `/cloglog setup` lets the next
  # `gh pr create` find the stale state.json and treat the shell as
  # registered, defeating the "not registered, call register_agent"
  # invariant the blocker hook is built around.
  rm -f "${MAIN_ROOT}/.cloglog/state.json" 2>> /tmp/agent-shutdown-debug.log || true
  exit 0
fi

WORKTREE_NAME=$(basename "$CWD")
# T-371 codex review round 4: Bash's reported `cwd` can be a nested
# subdirectory (e.g. `<worktree>/src`) — Claude does not pin it to the
# worktree root. Resolve the worktree root once and use it for the
# canonical state.json path AND the unregister-by-path payload, so
# both sides agree on what `worktree_path` means even when the agent
# happened to `cd` somewhere deeper before exiting. Falls back to
# `$CWD` if the resolution fails (e.g. very early shell teardown
# breaks `git rev-parse`); the rm then degrades to best-effort.
WORKTREE_ROOT=$(cd "$CWD" && git rev-parse --show-toplevel 2>/dev/null) || WORKTREE_ROOT="$CWD"
ARTIFACTS_DIR="${CWD}/shutdown-artifacts"
mkdir -p "$ARTIFACTS_DIR"

# --- Find config ---
find_config() {
  local dir="$1"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/.cloglog/config.yaml" ]]; then
      echo "$dir/.cloglog/config.yaml"
      return 0
    fi
    dir=$(dirname "$dir")
  done
  local repo_root
  repo_root=$(cd "$1" && git rev-parse --show-toplevel 2>/dev/null) || return 1
  if [[ -f "$repo_root/.cloglog/config.yaml" ]]; then
    echo "$repo_root/.cloglog/config.yaml"
    return 0
  fi
  return 1
}

CONFIG=$(find_config "$CWD") || true

BACKEND_URL="http://localhost:8000"
if [[ -n "$CONFIG" ]]; then
  # Read backend_url via a small grep+sed rather than python/yaml:
  # the system `python3` on many machines lacks `pyyaml` (the project's
  # pyyaml lives in the uv venv, not the global python the hook runs
  # under), so the previous python snippet silently returned the
  # default and the unregister POST went to the wrong port.
  parsed=$(grep '^backend_url:' "$CONFIG" | head -1 \
           | sed 's/^backend_url:[[:space:]]*//' \
           | sed 's/[[:space:]]*#.*$//' \
           | tr -d '"'"'")
  [[ -n "$parsed" ]] && BACKEND_URL="$parsed"
fi

# --- Resolve API key ---
# T-214: env or ~/.cloglog/credentials* only. The project key MUST NOT live
# inside any per-worktree file.
# T-382: lookup order is env → ~/.cloglog/credentials.d/<project_slug> →
# ~/.cloglog/credentials. Mirrors mcp-server/src/credentials.ts and the
# launch SKILL `_api_key` helper. On a multi-project host where the
# project's key only lives under credentials.d/<slug>, the legacy-only
# resolver here previously fell through to "no API_KEY" and the SessionEnd
# unregister POST got skipped — leaving the worktree registered until the
# heartbeat timeout instead of unregistering immediately.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/resolve-api-key.sh
source "${HOOK_DIR}/lib/resolve-api-key.sh"
API_KEY=$(resolve_api_key "$CONFIG")

# --- Generate shutdown artifacts ---
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

# --- T-243: emit agent_unregistered event to the main agent inbox ---
# Best-effort backstop. The agent SHOULD have written this event itself
# before calling unregister_agent (see ${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md §2 step 5);
# we always write here too because `zellij action close-tab` under close-wave
# has historically skipped this hook (T-217), so when the hook DOES fire we
# want the close-wave consumer to see the event even if the agent never ran
# step 5. The consumer deduplicates on (worktree, ts) and keeps the richer
# agent-written record when both are present. (worktree_id is NOT part of the
# dedup key because this hook has no access to the UUID — it lives in backend
# state, not the worktree filesystem.)
# $GIT_COMMON is the absolute path to the main clone's .git directory; its
# parent is the project root. $(git rev-parse --show-toplevel) is NOT
# equivalent — from a worktree it returns the worktree path, not the main
# clone, which would send the event to the wrong inbox.
PROJECT_ROOT=$(dirname "$GIT_COMMON")
MAIN_INBOX="${PROJECT_ROOT}/.cloglog/inbox"
mkdir -p "$(dirname "$MAIN_INBOX")" 2>/dev/null || true

TASKS_JSON='[]'
if tasks_raw=$(cd "$CWD" && git log --pretty=%s%n%b main..HEAD 2>/dev/null); then
  TASKS_JSON=$(printf '%s\n' "$tasks_raw" | jq -Rn '[inputs | scan("T-[0-9]+")] | unique')
fi

# T-262: best-effort enrichment of the (task -> PR URL) map. The agent's own
# emit (Section 2 step 5) is the authoritative source — it walks
# `get_my_tasks` and reads each row's `pr_url`. The hook has no MCP access
# and runs after the worktree may already be torn down, so we use a single
# `gh pr list --state merged --head <branch>` call to recover the map from
# GitHub. Missing `gh`, missing auth, or no merged PR yields `prs: {}` —
# consumers MUST treat the field as advisory: presence of a key is correct,
# absence is "hook didn't know," not "no PR exists."
PRS_JSON='{}'
if command -v gh >/dev/null 2>&1 && [[ "$TASKS_JSON" != "[]" ]]; then
  if prs_raw=$(cd "$CWD" && gh pr list --state merged --head "$WORKTREE_NAME" \
                  --json number,url,title,body --limit 50 2>/dev/null); then
    PRS_JSON=$(jq -c --argjson tasks "$TASKS_JSON" '
      ([.[] as $pr
        | (($pr.title // "") + " " + ($pr.body // "")) as $text
        | [($text | scan("T-[0-9]+"))] as $hits
        | $hits[] | {key: ., value: $pr.url}
       ] | from_entries)
      | with_entries(select(.key as $k | $tasks | index($k)))
    ' <<<"$prs_raw" 2>/dev/null) || PRS_JSON='{}'
  fi
fi

TS=$(date -Iseconds)
jq -cn \
  --arg wt "$WORKTREE_NAME" \
  --arg ts "$TS" \
  --arg wl "${ARTIFACTS_DIR}/work-log.md" \
  --arg ln "${ARTIFACTS_DIR}/learnings.md" \
  --argjson tasks "$TASKS_JSON" \
  --argjson prs "$PRS_JSON" \
  '{type:"agent_unregistered", worktree:$wt, ts:$ts, tasks_completed:$tasks,
    prs:$prs,
    artifacts:{work_log:$wl, learnings:$ln},
    reason:"best_effort_backstop_from_session_end_hook"}' \
  >> "$MAIN_INBOX" 2>> /tmp/agent-shutdown-debug.log || true

echo "[$(date -Iseconds)] agent-shutdown.sh wrote agent_unregistered backstop to ${MAIN_INBOX}" >> /tmp/agent-shutdown-debug.log

# --- Call unregister-by-path ---
# NOTE: append to the debug log rather than overwriting — the top-of-script
# breadcrumb (T-217) must survive this call so we can tell the hook fired
# even if the POST fails or API_KEY is absent.
if [[ -n "$API_KEY" ]]; then
  echo "[$(date -Iseconds)] agent-shutdown.sh calling unregister-by-path backend=${BACKEND_URL}" >> /tmp/agent-shutdown-debug.log
  curl -s --max-time 5 -X POST "${BACKEND_URL}/api/v1/agents/unregister-by-path" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    -d "{
      \"worktree_path\": \"${WORKTREE_ROOT}\",
      \"artifacts\": {
        \"work_log\": \"${ARTIFACTS_DIR}/work-log.md\",
        \"learnings\": \"${ARTIFACTS_DIR}/learnings.md\"
      }
    }" >> /tmp/agent-shutdown-debug.log 2>&1 || true
else
  echo "[$(date -Iseconds)] agent-shutdown.sh: no API_KEY — skipping unregister-by-path (will rely on tier-3 heartbeat timeout)" >> /tmp/agent-shutdown-debug.log
fi

# T-371: drop the per-worktree state.json so the require-task-for-pr hook
# does not treat a stale agent_token as proof the shell is still
# registered. SessionEnd is one of the project's normal shutdown paths
# (the other being the MCP unregister_agent tool, which has its own
# clearWorktreeState call); without this rm the next gh pr create in
# the surviving checkout falls into the hook's "unexpected response"
# branch instead of the intended "not registered, call register_agent"
# branch (codex review on PR #287, CRITICAL).
rm -f "${WORKTREE_ROOT}/.cloglog/state.json" 2>> /tmp/agent-shutdown-debug.log || true

exit 0
