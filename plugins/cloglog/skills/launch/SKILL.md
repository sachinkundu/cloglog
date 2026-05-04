---
name: launch
description: Launch worktree agents for features or tasks. Handles the full lifecycle — clean state check, task resolution, prompt assembly, agent launch with worktree isolation, and zellij tab management.
user-invocable: true
---

# Launch Worktree Agents

Launch isolated agents for features or tasks. Each agent gets its own worktree, runs autonomously, and follows the full pipeline.

**Usage:**
```
/cloglog launch F-12          # launch agent for a feature
/cloglog launch T-45 T-46     # launch agents for standalone tasks
```

Arguments: `$ARGUMENTS` — one or more feature (F-*) or task (T-*) identifiers.

## Step 1: Pre-flight Checks

### 1a. Check for uncommitted changes

Run `git status`. If there are uncommitted changes, STOP and commit or stash them first. Worktrees branch from HEAD and inherit dirty state — agents will see those diffs and think it's their work. This is non-negotiable.

### 1b. Resolve entity IDs

Parse `$ARGUMENTS` to extract feature/task identifiers (F-*, T-*) — `/cloglog launch` only accepts features and standalone tasks; epics (`E-*`) are containers and have no launch semantics in Steps 2-4 or the agent template. For each identifier, call `mcp__cloglog__search` with the entity-number token (e.g. `T-45`, `F-12`) — a single call returns the matching `id`/`type`/`number`/`title`/`status`/`model` (and parent epic + feature for tasks), so you never have to page the full board to turn `T-NNN` into a UUID. For tasks, capture the `model` field — it drives the `--model` flag passed to claude at launch (e.g. `claude-opus-4-7` for reasoning-heavy spec/plan tasks, `claude-sonnet-4-6` for implementation).

Fall back to `mcp__cloglog__get_board` / `mcp__cloglog__list_features` / `mcp__cloglog__get_active_tasks` only when you genuinely need to *enumerate* (e.g. "list every backlog task in this feature") rather than resolve a known number.

**Never `psql` the board** to look up an ID. The MCP server is the only sanctioned read path; raw SQL bypasses the agent-token auth checks and can drift out of sync with the API contract.

### 1c. Check task status

Only launch agents for tasks in `backlog` status. Skip tasks that are already `in_progress`, `review`, or `done`. Warn the user about skipped tasks.

### 1d. Assess conflict risk

If multiple tasks touch the same areas, warn the user about merge conflict risk but proceed if they confirm.

## Step 2: Prepare Pipeline Tasks (Features Only)

For each feature (F-*), ensure the three pipeline tasks exist:

1. **spec** — "Write design spec for F-*"
2. **plan** — "Write implementation plan for F-*"
3. **impl** — "Implement F-*"

Use `mcp__cloglog__create_task` to create any missing pipeline tasks. The state machine guards enforce ordering — the agent cannot start plan until spec is done, cannot start impl until plan is done.

**Model assignment for pipeline tasks:** Assign models when creating tasks — spec and plan are reasoning-heavy and should use `claude-opus-4-7`; impl is mechanical and should use `claude-sonnet-4-6`. Pass `model` to `mcp__cloglog__create_task`. If the task already exists (returned by search), its model field is already set from prior creation and you do not need to update it.

After ensuring all pipeline tasks exist, resolve `TASK_MODEL` for the launch step: call `mcp__cloglog__get_active_tasks` (or re-use the search result from Step 1b) to find the first backlog/in-progress pipeline task for this feature, and capture its `model` field as `TASK_MODEL`. This ensures `TASK_MODEL` is set correctly even for feature launches where Step 1b only resolved the F-* identifier.

For standalone tasks (T-*), skip this step — they are executed directly.

## Step 3: Assemble Agent Prompt

Workflow rules live in **one file** — `${CLAUDE_PLUGIN_ROOT}/templates/AGENT_PROMPT.md` — and are copied verbatim into each worktree. The per-task delta lives in a small sibling `task.md`. Hand-pasting workflow rules into per-agent prompts is the failure mode T-360 closed (2026-04-30: three agents tailing the wrong inbox file because authors hand-copied the inbox path).

For each task or feature:

```bash
# 1. Copy the workflow template verbatim. The template is the single source
# of truth for inbox handling, MCP preload, stop-on-failure, the standard
# workflow, the per-task shutdown sequence, and the continuation prompt.
cp "${CLAUDE_PLUGIN_ROOT}/templates/AGENT_PROMPT.md" "${WORKTREE_PATH}/AGENT_PROMPT.md"

# 2. Emit the per-task delta. Use a **quoted** heredoc (`'TASK_EOF'`) so
# `${VAR}` references in the body stay literal — only the `@@PLACEHOLDER@@`
# tokens get substituted via sed below. Mirrors T-353's quoted-heredoc
# discipline for launch.sh.
cat > "${WORKTREE_PATH}/task.md" << 'TASK_EOF'
# Task — @@TASK_NUMBER@@: @@TASK_TITLE@@

Priority: @@PRIORITY@@
Feature: @@FEATURE_REF@@

## Task IDs
- Task ID: `@@TASK_UUID@@`
- Feature ID: `@@FEATURE_UUID@@`
- Worktree ID: `@@WORKTREE_UUID@@`
- Worktree name: `@@WORKTREE_NAME@@`
- Worktree path: `@@WORKTREE_PATH@@`
- Project root: `@@PROJECT_ROOT@@`

## Description

@@TASK_DESCRIPTION@@

## Sibling work in flight

@@SIBLING_WARNINGS@@

## Residual TODOs hint

@@RESIDUAL_NOTES@@
TASK_EOF

# 3. Substitute per-task placeholders. Task titles / descriptions are
# free-form board strings (src/board/schemas.py:133-139) so they may
# contain `&` (which sed expands to the matched text), `\` (escape), or
# the chosen `|` delimiter. Without escaping, a title like `R&D follow-up`
# would render `task.md` with the placeholder text spliced back in.
# `_sed_escape_replacement` escapes the three replacement metacharacters
# so every value round-trips literally.
_sed_escape_replacement() {
  printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'
}
TASK_NUMBER_E=$(_sed_escape_replacement "${TASK_NUMBER}")
TASK_TITLE_E=$(_sed_escape_replacement "${TASK_TITLE}")
PRIORITY_E=$(_sed_escape_replacement "${PRIORITY}")
FEATURE_REF_E=$(_sed_escape_replacement "${FEATURE_REF:-(none)}")
TASK_UUID_E=$(_sed_escape_replacement "${TASK_UUID}")
FEATURE_UUID_E=$(_sed_escape_replacement "${FEATURE_UUID:-(none)}")
WORKTREE_UUID_E=$(_sed_escape_replacement "${WORKTREE_UUID}")
WORKTREE_NAME_E=$(_sed_escape_replacement "${WORKTREE_NAME}")
WORKTREE_PATH_E=$(_sed_escape_replacement "${WORKTREE_PATH}")
PROJECT_ROOT_E=$(_sed_escape_replacement "${PROJECT_ROOT}")

sed -i \
  -e "s|@@TASK_NUMBER@@|${TASK_NUMBER_E}|g" \
  -e "s|@@TASK_TITLE@@|${TASK_TITLE_E}|g" \
  -e "s|@@PRIORITY@@|${PRIORITY_E}|g" \
  -e "s|@@FEATURE_REF@@|${FEATURE_REF_E}|g" \
  -e "s|@@TASK_UUID@@|${TASK_UUID_E}|g" \
  -e "s|@@FEATURE_UUID@@|${FEATURE_UUID_E}|g" \
  -e "s|@@WORKTREE_UUID@@|${WORKTREE_UUID_E}|g" \
  -e "s|@@WORKTREE_NAME@@|${WORKTREE_NAME_E}|g" \
  -e "s|@@WORKTREE_PATH@@|${WORKTREE_PATH_E}|g" \
  -e "s|@@PROJECT_ROOT@@|${PROJECT_ROOT_E}|g" \
  "${WORKTREE_PATH}/task.md"

# 4. Multi-line placeholders. Description / sibling warnings / residual
# notes are free-form multi-line strings — sed's replacement-string
# substitution doesn't handle newlines cleanly, so we write each value
# to a temp file and use sed's `r FILE` + `d` pair to replace the whole
# placeholder line with the file's contents. Each placeholder appears
# on its own line in the heredoc above, which makes whole-line
# replacement safe.
#
# Codex round 4 (HIGH): no `WORKFLOW_OVERRIDE` placeholder. The board /
# MCP contracts have no persisted `workflow_override` field; the
# template handles `skip_pr` as a runtime decision the agent makes from
# its own diff at PR time, not as a launch-time stored field.
TMP_DESC=$(mktemp)
TMP_SIB=$(mktemp)
TMP_RES=$(mktemp)
trap 'rm -f "$TMP_DESC" "$TMP_SIB" "$TMP_RES"' EXIT

printf '%s' "${TASK_DESCRIPTION:-(none)}"   > "$TMP_DESC"
printf '%s' "${SIBLING_WARNINGS:-(none)}"   > "$TMP_SIB"
printf '%s' "${RESIDUAL_NOTES:-(none)}"     > "$TMP_RES"

# `sed -i -e '/@@TOKEN@@/{r FILE' -e 'd}'` reads FILE in place of the
# matched line, then deletes the placeholder. Two `-e` arguments are
# required because the `r` command extends to end-of-line.
sed -i -e "/@@TASK_DESCRIPTION@@/{r ${TMP_DESC}" -e "d;}" "${WORKTREE_PATH}/task.md"
sed -i -e "/@@SIBLING_WARNINGS@@/{r ${TMP_SIB}"  -e "d;}" "${WORKTREE_PATH}/task.md"
sed -i -e "/@@RESIDUAL_NOTES@@/{r ${TMP_RES}"    -e "d;}" "${WORKTREE_PATH}/task.md"
```

The agent reads `AGENT_PROMPT.md` first; the template's first section instructs it to read `task.md` for the per-task delta. The launch.sh fallback prompt (`Read ${WORKTREE_PATH}/AGENT_PROMPT.md and begin.`) is unchanged — `task.md` is reached transitively from the template.

### What the template owns vs. what task.md owns

- **Template (`plugins/cloglog/templates/AGENT_PROMPT.md`):** inbox paths (worktree for read, project root for write), MCP preload, stop-on-MCP-failure, standard workflow steps, per-task shutdown sequence, runtime `skip_pr` decision rule, continuation-prompt bootstrap, work-log bootstrap. Update this file once and every future agent inherits the change.
- **`task.md`:** task ID / feature ID / worktree ID / paths, task number / title / priority, description, sibling-task warnings, residual TODOs hint.

### Standalone no-PR tasks (runtime `skip_pr`)

A task that finishes without a PR (docs / research / prototype / internal-only refactor) is recognised at runtime, not at launch — the agent inspects its own diff at PR time and either calls `update_task_status(task_id, "review", skip_pr=True)` or opens a PR. There is no persisted `workflow_override` field on the board (`src/agent/schemas.py:60-65`, `mcp-server/src/tools.ts:29-35` expose `skip_pr` only at status-update time). See the template's **Standalone no-PR tasks** section for the diff-based decision rule.

## One task per session

Each worktree agent runs exactly one task per session and exits after the PR merges (or after a `skip_pr` standalone task completes). The supervisor sees `agent_unregistered`, runs the relaunch flow below, and either issues the continuation prompt or triggers `cloglog:close-wave`. Plan tasks are the only exception — a plan task immediately starts the following impl task in the same session; the boundary fires when the impl PR merges.

Full per-task shutdown sequence lives in `${CLAUDE_PLUGIN_ROOT}/templates/AGENT_PROMPT.md` under **Per-task shutdown sequence**.

## Continuation Prompt

When the supervisor relaunches the same worktree for task N+1, it issues:

```
Read ${WORKTREE_PATH}/AGENT_PROMPT.md and all shutdown-artifacts/work-log-T-*.md files in ${WORKTREE_PATH}, then begin the next task.
```

The new session reads the template (already on disk in the worktree from the original launch), reads prior work logs, loads MCP tools, **re-registers via `mcp__cloglog__register_agent` to bind the new MCP session** (the previous session's `unregister_agent` cleared its per-process state), then follows Standard workflow step 3 unchanged: trust `task.md`'s UUID and call `start_task`. There is **one** task-resolution contract — the same one initial launches use.

**The launch SKILL writes the initial prompt; the supervisor writes continuation prompts.** Continuation sessions reuse `.cloglog/launch.sh` by passing the prompt as `$1` so the TERM/HUP signal trap and `_unregister_fallback` path from the initial launch are preserved.

**Required: supervisor-side `task.md` rewrite.** The supervisor MUST rewrite `${WORKTREE_PATH}/task.md` for the next task before issuing the continuation prompt — using the same Step 3 rendering shape this skill uses on initial launch. That edit lands in the Supervisor Relaunch Flow section, which T-356 currently owns. Until it ships, the very first `start_task` after relaunch hits a 409 because `task.md` still names the just-merged task; the agent emits `mcp_tool_error` and halts (fail-loud-fast). The agent does NOT fall back to `get_my_tasks` because `TaskInfo` does not expose `task_type` (`src/agent/schemas.py:67-78`) and an agent-side resolver cannot reproduce the supervisor's pipeline-aware pick.

## Supervisor Relaunch Flow

When the supervisor inbox receives `agent_unregistered` from a worktree agent:

1. Extract the `worktree_id` from the `agent_unregistered` event.
2. Call `mcp__cloglog__get_active_tasks` to get all non-done tasks in the project. Filter the result to tasks where `worktree_id == <unregistered worktree's uuid>` AND `status == "backlog"`. **Do NOT use `mcp__cloglog__get_my_tasks`** — that returns tasks scoped to the supervisor's own worktree registration, not the worktree that just unregistered.
3. **If backlog tasks remain** → relaunch in the same zellij tab:
   ```bash
   # Update task-model for the next task (T-332) — launch.sh reads this at
   # runtime, so writing it before relaunch gives the new session its correct model.
   # NEXT_TASK_MODEL comes from the backlog task's `model` field in get_active_tasks.
   printf '%s\n' "${NEXT_TASK_MODEL:-}" > "${WORKTREE_PATH}/.cloglog/task-model"

   # Go to the worktree's tab (same tab name as WORKTREE_NAME)
   zellij action go-to-tab-by-name "${WORKTREE_NAME}"
   # Issue the continuation prompt — the tab's current process has exited,
   # so the shell is at the prompt again
   zellij action write-chars "bash '${WORKTREE_PATH}/.cloglog/launch.sh' 'Read ${WORKTREE_PATH}/AGENT_PROMPT.md and all shutdown-artifacts/work-log-T-*.md files in ${WORKTREE_PATH}, then begin the next task.'"
   zellij action write "13"   # send Enter
   ```
4. **Confirmation phase applies to relaunches too.** A continuation prompt can trip the same bootstrap failures as an initial launch — `claude` can fail to start, the new task's `--model` can be unavailable, MCP can be down, the heredoc-rendered `launch.sh` can have decayed (T-353-class issue introduced by an unrelated edit). After issuing the relaunch keystrokes, watch `<project_root>/.cloglog/inbox` for an `agent_started` event whose `worktree` field equals `${WORKTREE_NAME}`, with the same `launch_confirm_timeout_seconds` deadline (default `90`) as Step 5. On timeout, emit the same diagnostic checklist (`list-tabs --json | jq` / `bash -n` / `agent-shutdown-debug.log` / split `CLOGLOG_API_KEY` (env first; for repos with `project_id` in `config.yaml` check `~/.cloglog/credentials.d/<project_slug>`; legacy fallback `~/.cloglog/credentials` when no `project_id` is set) and `DATABASE_URL` (`.env`) probes / `head -3 launch.sh`) and hand off to the operator. **Do NOT silently retry the relaunch; do NOT loop up to N times.** The supervisor must NOT mark the worktree as continuing on the next task until either `agent_started` arrives or the operator has acted.
5. **If no backlog tasks remain** → invoke the `cloglog:close-wave` skill for this worktree.

## Pipeline behaviour (Features Only)

For features with spec/plan/impl tasks, agent behaviour is defined in `${CLAUDE_PLUGIN_ROOT}/agents/worktree-agent.md` under **Pipeline Lifecycle**. Summary:

- **Spec task:** write design spec, open PR, wait for merge. On merge: `mark_pr_merged` → `report_artifact` → per-task work log → `agent_unregistered` → exit. Supervisor relaunches for plan.
- **Plan task:** write plan, commit locally, `update_task_status(plan_task_id, "review", skip_pr=True)` + `report_artifact`, then `start_task` on the impl in the same session. **Known backend gap (T-NEW-b):** `start_task` on the impl returns 409 until the pipeline guard at `src/agent/services.py:237` accepts artifact-only predecessor resolution; emit `mcp_tool_error` with `reason: "pipeline_guard_blocked"` to the main inbox and stop. See `${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md` §1.
- **Impl task:** implement, open PR, wait for merge. On merge: per-task work log → `agent_unregistered` → exit.

The supervisor sees `agent_unregistered`, runs the relaunch flow above, and either relaunches or triggers `cloglog:close-wave`.

## Step 4: Create Worktrees and Launch Agents

For each task/feature, launch sequentially (not in parallel):

### 4a. Create the git worktree

```bash
WORKTREE_NAME="wt-<descriptive-name>"
WORKTREE_PATH="$(git rev-parse --show-toplevel)/.claude/worktrees/${WORKTREE_NAME}"
git fetch origin main
git worktree add -b "${WORKTREE_NAME}" "${WORKTREE_PATH}" origin/main
```

**IMPORTANT:** Always branch from `origin/main`, never `HEAD`. Local main may have unpushed commits that would leak into the worktree's PR diff as unrelated changes.

### 4b. Register agent on the board

Call `mcp__cloglog__register_agent` with the worktree name and path. This is done here (not deferred to the agent) so the board reflects the launch immediately.

**Run this before Step 4c.** The project-specific `on-worktree-create.sh` posts to `/api/v1/agents/close-off-task`, which requires the worktree to be registered first; if 4c runs before 4b the backend returns HTTP 404 and (with T-378's fail-loud) the bootstrap aborts. Memory 2026-04-24: "always register agent first" — pinned by `tests/plugins/test_launch_skill_register_before_on_worktree_create.py`.

### 4c. Run project-specific worktree setup

If the project has `.cloglog/on-worktree-create.sh`, run it. **Use absolute paths and pass `WORKTREE_PATH` as an env var — never `cd` into the new worktree.** The Bash tool's shell persists `cwd` between calls, so a `cd` into the new worktree leaks into every subsequent main-agent command and the main agent ends up looking like it's working inside the worktree it just spawned.

```bash
if [[ -x "${WORKTREE_PATH}/.cloglog/on-worktree-create.sh" ]]; then
  WORKTREE_PATH="${WORKTREE_PATH}" WORKTREE_NAME="${WORKTREE_NAME}" "${WORKTREE_PATH}/.cloglog/on-worktree-create.sh"
fi
```

### 4d. AGENT_PROMPT.md and task.md

Step 3 already wrote both `${WORKTREE_PATH}/AGENT_PROMPT.md` (verbatim copy of the workflow template) and `${WORKTREE_PATH}/task.md` (per-task delta). Nothing further to do here.

### 4e. Create zellij tab and launch agent

```bash
# Capture current tab's stable numeric ID before switching away.
# T-384: read from `list-tabs --json` — single contract used everywhere
# (close-zellij-tab.sh helper, supervisor relaunch flow, here). The
# `.active` boolean on each tab payload identifies the focused tab.
CURRENT_TAB_ID=$(zellij action list-tabs --json 2>/dev/null \
  | jq -r '.[] | select(.active) | .tab_id')

# Resolve the project root so the launcher can read backend_url and (as a
# fallback) the MCP API key. Falls back to the current repo.
PROJECT_ROOT="$(git rev-parse --show-toplevel)"

# Write task model for launch.sh — update before each relaunch with the next task's model
# TASK_MODEL comes from the task's `model` field resolved in Step 1b (may be empty)
printf '%s\n' "${TASK_MODEL:-}" > "${WORKTREE_PATH}/.cloglog/task-model"

# Write a launcher script. T-353: the heredoc is **quoted** (`<< 'EOF'`) so bash
# performs zero expansion inside it — `$1`, `$2`, `${...}` all survive verbatim
# and need no `\` escaping. The two operator-host-specific values
# (`WORKTREE_PATH`, `PROJECT_ROOT`) are baked in afterwards via `sed -i` against
# `@@WORKTREE_PATH@@` / `@@PROJECT_ROOT@@` placeholders. Earlier revisions used
# an unquoted heredoc with `\$1`/`\$2` escapes, which collapsed inconsistently
# when the SKILL block was relayed across the LLM-agent Bash-tool → bash
# boundary, producing rendered files like `local file="\"; local key="\"` and
# tripping `unexpected EOF while looking for matching '"'` at exec time.
# T-217: we do NOT use `exec claude` here. `exec` would replace the bash
# wrapper with claude, destroying any trap installed in this script — and a
# SIGTERM from close-wave (step 5) would then reach only claude, whose
# SessionEnd hook is best-effort under signal. By running claude as a
# subprocess and wait()ing for it, the TERM/HUP trap below fires reliably and
# we hit /agents/unregister-by-path directly before claude is killed. See
# `docs/agent-lifecycle.md` §2 and the T-217 experiment output (tab-close
# sends no signal at all; only the kill step does).
cat > "${WORKTREE_PATH}/.cloglog/launch.sh" << 'EOF'
#!/bin/bash
# Auto-generated by the cloglog launch skill. See plugins/cloglog/skills/launch/SKILL.md.
set -u

WORKTREE_PATH="@@WORKTREE_PATH@@"
PROJECT_ROOT="@@PROJECT_ROOT@@"

_backend_url() {
  # T-312: stdlib-only grep+sed scalar parse — same shape as the shared helper
  # at plugins/cloglog/hooks/lib/parse-yaml-scalar.sh. Inlined here because
  # launch.sh runs as a standalone bash exec inside the worktree, with no
  # CLAUDE_PLUGIN_ROOT in scope to source the helper from. Do NOT reintroduce
  # the python YAML lib here — the system python3 typically lacks PyYAML and
  # silently returns the default, breaking ports on portable hosts.
  local cfg="$PROJECT_ROOT/.cloglog/config.yaml"
  local default="http://localhost:8000"
  [[ -f "$cfg" ]] || { echo "$default"; return; }
  local parsed
  parsed=$(grep '^backend_url:' "$cfg" 2>/dev/null | head -n1 \
           | sed 's/^backend_url:[[:space:]]*//' \
           | sed 's/[[:space:]]*#.*$//' \
           | tr -d '"' | tr -d "'")
  if [[ -n "$parsed" ]]; then echo "$parsed"; else echo "$default"; fi
}

_read_scalar_yaml() {
  # T-348: read a top-level scalar key from a YAML file via grep+sed.
  # Same shape as _backend_url and parse-yaml-scalar.sh; do NOT reintroduce
  # the python YAML lib here (docs/invariants.md:76 — system python3
  # typically lacks PyYAML and silently returns the default).
  local file="$1"; local key="$2"
  [[ -f "$file" ]] || return 0
  grep "^${key}:" "$file" 2>/dev/null | head -n1 \
    | sed "s/^${key}:[[:space:]]*//" \
    | sed 's/[[:space:]]*#.*$//' \
    | tr -d '"' | tr -d "'"
}

_gh_app_id() {
  # Resolution order (T-348): env → .cloglog/local.yaml (gitignored,
  # host-local — preferred) → .cloglog/config.yaml (tracked fallback for
  # single-operator repos). Mirrors gh-app-token.py's _resolve precedence
  # exactly so an operator who keeps a temporary env override is honored,
  # not clobbered by stale YAML.
  [[ -n "${GH_APP_ID:-}" ]] && { echo "$GH_APP_ID"; return; }
  local v
  v=$(_read_scalar_yaml "$PROJECT_ROOT/.cloglog/local.yaml" "gh_app_id")
  [[ -n "$v" ]] && { echo "$v"; return; }
  _read_scalar_yaml "$PROJECT_ROOT/.cloglog/config.yaml" "gh_app_id"
}

_gh_app_installation_id() {
  # See _gh_app_id resolution order above (env first).
  [[ -n "${GH_APP_INSTALLATION_ID:-}" ]] && { echo "$GH_APP_INSTALLATION_ID"; return; }
  local v
  v=$(_read_scalar_yaml "$PROJECT_ROOT/.cloglog/local.yaml" "gh_app_installation_id")
  [[ -n "$v" ]] && { echo "$v"; return; }
  _read_scalar_yaml "$PROJECT_ROOT/.cloglog/config.yaml" "gh_app_installation_id"
}

_project_slug() {
  # T-382: derive the per-project credential slug. Reads `project:` from
  # .cloglog/config.yaml, falls back to basename($PROJECT_ROOT). Mirrors
  # resolveProjectSlug() in mcp-server/src/credentials.ts. Validates against
  # [A-Za-z0-9._-] to refuse path-traversal — anything else returns empty
  # and the caller falls through to the legacy global credentials file.
  local re='^[A-Za-z0-9._-]+$'
  local slug
  slug=$(_read_scalar_yaml "$PROJECT_ROOT/.cloglog/config.yaml" "project")
  if [[ -n "$slug" && "$slug" =~ $re ]]; then
    echo "$slug"; return
  fi
  slug=$(basename "$PROJECT_ROOT")
  if [[ -n "$slug" && "$slug" =~ $re ]]; then
    echo "$slug"
  fi
}

_read_credentials_file() {
  # Stripped-down version of credentials.ts parseCredentialsFile: pull the
  # CLOGLOG_API_KEY value out of a KEY=VALUE file, stripping surrounding
  # single/double quotes. Empty result on miss so the caller can fall through.
  local cred="$1"
  [[ -r "$cred" ]] || return 0
  local v
  v=$(grep '^CLOGLOG_API_KEY=' "$cred" 2>/dev/null | head -n 1 | cut -d= -f2-)
  v=${v%\"}; v=${v#\"}; v=${v%\'}; v=${v#\'}
  [[ -n "$v" ]] && echo "$v"
}

_api_key() {
  # T-382 — per-project credential resolution. Lookup order matches
  # mcp-server/src/credentials.ts loadApiKey and the shared hook helper at
  # plugins/cloglog/hooks/lib/resolve-api-key.sh:
  #   1. CLOGLOG_API_KEY env (operator override)
  #   2. ~/.cloglog/credentials.d/<project_slug>  (per-project)
  #   3. ~/.cloglog/credentials                   (legacy global)
  # The per-project file solves the multi-project-host bug where the global
  # file held the wrong project's key and agent calls earned silent 401s on
  # /api/v1/agents/unregister-by-path. Single-project hosts keep working
  # unchanged via the legacy fallback. The worktree's .env and the repo's
  # .mcp.json MUST NOT carry the key — tests/test_mcp_json_no_secret.py
  # pins that invariant and .cloglog/on-worktree-create.sh never writes
  # the key to .env.
  #
  # Fail-loud invariant: once ~/.cloglog/credentials.d/<slug> EXISTS, it
  # must yield a usable key. Present-but-unreadable / present-but-empty /
  # present-as-directory MUST NOT fall through to the legacy global file —
  # the global file may belong to a different project, and silently
  # sending its key recreates the original silent-401 bug. On the
  # present-but-unusable path we log to /tmp/agent-shutdown-debug.log
  # and return empty so the trap-fired _unregister_fallback skips the POST
  # instead of authenticating as the wrong project.
  [[ -n "${CLOGLOG_API_KEY:-}" ]] && { echo "$CLOGLOG_API_KEY"; return; }
  local slug v
  slug=$(_project_slug)
  if [[ -n "$slug" ]]; then
    local proj_file="${HOME}/.cloglog/credentials.d/${slug}"
    if [[ -e "$proj_file" ]]; then
      if [[ ! -r "$proj_file" ]]; then
        echo "[$(date -Iseconds)] launch.sh _api_key: ${proj_file} exists but unreadable; refusing legacy fallback (T-382)" \
          >> /tmp/agent-shutdown-debug.log 2>&1 || true
        return 0
      fi
      if [[ -d "$proj_file" ]]; then
        echo "[$(date -Iseconds)] launch.sh _api_key: ${proj_file} is a directory; refusing legacy fallback (T-382)" \
          >> /tmp/agent-shutdown-debug.log 2>&1 || true
        return 0
      fi
      v=$(_read_credentials_file "$proj_file")
      [[ -n "$v" ]] && { echo "$v"; return; }
      echo "[$(date -Iseconds)] launch.sh _api_key: ${proj_file} present but no CLOGLOG_API_KEY; refusing legacy fallback (T-382)" \
        >> /tmp/agent-shutdown-debug.log 2>&1 || true
      return 0
    fi
  fi
  # T-398 Guard 3: if project_id is set in config.yaml but no per-project
  # credentials file was found, refuse the legacy global fallback. The MCP
  # server's loadApiKey and the shared hook helper resolve-api-key.sh enforce
  # the same rule — launch.sh must be consistent or the signal-trap
  # _unregister_fallback POST authenticates as the wrong project.
  local project_id
  project_id=$(_read_scalar_yaml "$PROJECT_ROOT/.cloglog/config.yaml" "project_id")
  if [[ -n "$project_id" ]]; then
    echo "[$(date -Iseconds)] launch.sh _api_key: project_id=${project_id} is set but credentials.d/${slug:-<no-slug>} is missing; refusing legacy fallback (T-398)" \
      >> /tmp/agent-shutdown-debug.log 2>&1 || true
    return 0
  fi
  # Legacy fallback — only safe on hosts where project_id is not set in
  # config.yaml (pre-T-382 single-project installs).
  v=$(_read_credentials_file "${HOME}/.cloglog/credentials")
  [[ -n "$v" ]] && { echo "$v"; return; }
  return 0
}

_unregister_fallback() {
  local sig="${1:-unknown}"
  local url="$(_backend_url)"
  local key="$(_api_key)"
  echo "[$(date -Iseconds)] launch.sh trap fired sig=$sig worktree=$WORKTREE_PATH" >> /tmp/agent-shutdown-debug.log
  if [[ -z "$key" ]]; then
    echo "[$(date -Iseconds)] launch.sh trap: no API key; skipping unregister POST" >> /tmp/agent-shutdown-debug.log
    return
  fi
  curl -s --max-time 5 -X POST "${url}/api/v1/agents/unregister-by-path" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${key}" \
    -d "{\"worktree_path\": \"${WORKTREE_PATH}\"}" \
    >> /tmp/agent-shutdown-debug.log 2>&1 || true
}

CLEANUP_DONE=0
_on_signal() {
  local sig="$1"
  [[ "$CLEANUP_DONE" == "1" ]] && return
  CLEANUP_DONE=1
  _unregister_fallback "$sig"
  if [[ -n "${CLAUDE_PID:-}" ]] && kill -0 "$CLAUDE_PID" 2>/dev/null; then
    kill -"$sig" "$CLAUDE_PID" 2>/dev/null || true
    # Give claude up to 5s to run its own SessionEnd hook before exiting.
    for _ in 1 2 3 4 5; do
      kill -0 "$CLAUDE_PID" 2>/dev/null || break
      sleep 1
    done
  fi
  exit 0
}
trap '_on_signal TERM' TERM
trap '_on_signal HUP' HUP
trap '_on_signal INT' INT

cd "$WORKTREE_PATH"
# T-348: export GitHub App identifiers so the github-bot skill's
# gh-app-token.py can mint installation tokens. These survive `/clear`
# because launch.sh re-exports them on every (re)launch, instead of
# relying on shell RC inheritance from whatever spawned zellij.
_GH_APP_ID="$(_gh_app_id)"
_GH_APP_INSTALLATION_ID="$(_gh_app_installation_id)"
[[ -n "$_GH_APP_ID" ]] && export GH_APP_ID="$_GH_APP_ID"
[[ -n "$_GH_APP_INSTALLATION_ID" ]] && export GH_APP_INSTALLATION_ID="$_GH_APP_INSTALLATION_ID"
# Read per-task model from .cloglog/task-model — written by the launch skill (T-332).
# The supervisor rewrites this file before each continuation relaunch so the
# correct model is used for every task, not just the initial one.
_MODEL_FLAG=""
_TASK_MODEL=$(cat "$WORKTREE_PATH/.cloglog/task-model" 2>/dev/null || true)
[[ -n "$_TASK_MODEL" ]] && _MODEL_FLAG="--model $_TASK_MODEL"
# Optional $1: continuation prompt string from supervisor relaunch.
# When absent, fall back to reading AGENT_PROMPT.md (initial launch).
_CLAUDE_PROMPT="${1:-Read @@WORKTREE_PATH@@/AGENT_PROMPT.md and begin.}"
# T-387: load the plugin live from the worktree's on-disk copy via
# `--plugin-dir`. Without this flag claude resolves the cloglog plugin
# from its install-time cache (`claude plugins install`), so edits made
# to plugins/cloglog/skills/**, hooks/**, or templates/** in this
# worktree are invisible to the agent until the operator manually
# reinstalls. Live-load makes plugin edits visible on the next agent
# launch — no `claude plugins install --force` dance required. The
# path must be absolute and rooted at THIS worktree's plugin source
# (each worktree carries its own copy of plugins/cloglog/), not a
# shared install — that is the whole point. Pinned by
# tests/plugins/test_launch_sh_loads_plugin_live.py.
_PLUGIN_DIR_FLAG=""
if [[ -d "$WORKTREE_PATH/plugins/cloglog" ]]; then
  _PLUGIN_DIR_FLAG="--plugin-dir $WORKTREE_PATH/plugins/cloglog"
fi
claude --dangerously-skip-permissions ${_MODEL_FLAG:+$_MODEL_FLAG} ${_PLUGIN_DIR_FLAG:+$_PLUGIN_DIR_FLAG} "$_CLAUDE_PROMPT" &
CLAUDE_PID=$!
wait "$CLAUDE_PID"
EOF
# T-353: substitute operator-host-specific paths into the rendered file.
# Quoted heredoc above leaves @@WORKTREE_PATH@@ / @@PROJECT_ROOT@@ as literal
# placeholders; sed bakes them in here. Use `|` as the separator since paths
# contain `/`.
#
# T-353 codex round 1 — escape the replacement string for sed. In a sed
# replacement, `&` expands to the matched text, `\` escapes, and the chosen
# delimiter `|` ends the replacement. Any host path containing `&`, `|`, or
# `\` (e.g. a repo under `~/R&D/`) would render with `&` replaced by the
# placeholder text and trip silent path corruption. The regex
# `'s/[&|\]/\\&/g'` prefixes a backslash to each of those three metacharacters
# in the replacement.
_sed_escape_replacement() { printf '%s' "$1" | sed 's/[&|\]/\\&/g'; }
_ESC_WORKTREE_PATH=$(_sed_escape_replacement "${WORKTREE_PATH}")
_ESC_PROJECT_ROOT=$(_sed_escape_replacement "${PROJECT_ROOT}")
sed -i "s|@@WORKTREE_PATH@@|${_ESC_WORKTREE_PATH}|g" "${WORKTREE_PATH}/.cloglog/launch.sh"
sed -i "s|@@PROJECT_ROOT@@|${_ESC_PROJECT_ROOT}|g" "${WORKTREE_PATH}/.cloglog/launch.sh"
chmod +x "${WORKTREE_PATH}/.cloglog/launch.sh"

# new-tab -- <command> starts the command in the tab's initial pane — no write-chars, no list-clients, no pane-id needed.
# T-384: chain new-tab + focus-back in one shell command. `new-tab` returns
# immediately and steals focus to the new tab; the chained `go-to-tab-by-id`
# fires before the visible swap so the supervisor sees no focus blink.
# Issuing them as separate Bash calls leaves a brief window where the
# supervisor's prompt is hidden.
zellij action new-tab --name "${WORKTREE_NAME}" -- bash "${WORKTREE_PATH}/.cloglog/launch.sh" \
  && zellij action go-to-tab-by-id "${CURRENT_TAB_ID}"
```

> **`launch.sh` is operator-host-specific.** The post-heredoc `sed -i`
> substitutions above bake the current operator's `${WORKTREE_PATH}` and
> `${PROJECT_ROOT}` absolute paths into the rendered script.
> The file is gitignored (`.gitignore`) so it is not a tracked source leak —
> but gitignored does **not** mean "safe to copy". Copying `launch.sh` between
> operators or hosts will produce a script that references non-existent paths on
> the target machine. Each host regenerates this file at launch time from its
> own current `WORKTREE_PATH`. Do not commit it, archive it, or hand it to
> another operator as a working artifact.

### 4f. One agent at a time

Wait briefly between each agent launch. Each needs its own zellij tab.

## Step 5: Verification

After all agents are launched, the main agent does NOT trust tab creation as proof of life. A spawned zellij tab can hold a crashed `claude`, a `bash` syntax error in `launch.sh` (e.g. T-353's antisocial heredoc bug — `unexpected EOF while looking for matching '"'`), a half-applied `on-worktree-create.sh`, or an MCP-unavailable abort, and `list-tabs --json` will still list the tab. The only authoritative liveness signal is an `agent_started` event on `<project_root>/.cloglog/inbox` carrying the worktree's `worktree` field. Step 5 enforces a deadline on that event per launched worktree.

1. **List tabs** to confirm all were created:
   ```bash
   zellij action list-tabs --json | jq -r '.[].name'
   ```

2. **Confirmation phase — `agent_started` deadline.** For each launched worktree, watch `<project_root>/.cloglog/inbox` for an `agent_started` event whose `worktree` field equals the worktree name (e.g. `wt-t356-launch-confirm-timeout`). The deadline is `launch_confirm_timeout_seconds` from `.cloglog/config.yaml` (default `90` if the key is missing or malformed — read via the `parse-yaml-scalar.sh` shape, do NOT introduce a YAML library). The main agent already runs a persistent inbox Monitor — reuse it; do not spawn a second tail. Read the existing event stream with a deadline (e.g. an `until`-loop over `tail -F` filtered to `agent_started` lines for this `worktree`, bounded by `date +%s` against `start + launch_confirm_timeout_seconds`).

   - **Confirmed within deadline** → row in the summary table is marked `live` and carries the `worktree_id` from the event payload.
   - **Deadline elapsed with no matching event** → row is marked `LAUNCH FAILED — no agent_started in <N>s`. The main agent emits the diagnostic checklist below and **hands off to the operator**. The main agent does NOT silently retry; do NOT loop on the launch up to N times; every class of bootstrap failure has a different fix and the operator owns the call.

3. **Diagnostic checklist on timeout.** Print these commands verbatim for the operator (substitute `<worktree>` with the absolute worktree path and `<wt-name>` with the tab/branch name):

   1. `zellij action list-tabs --json | jq -r --arg n "<wt-name>" '.[] | select(.name == $n) | .tab_id'` — tab present? Empty ⇒ launcher never ran.
   2. `bash -n <worktree>/.cloglog/launch.sh` — syntax valid? Non-zero ⇒ heredoc-rendering failure (T-353 class).
   3. `tail -20 /tmp/agent-shutdown-debug.log` — any trap fire mentioning this worktree? Process started then died on signal.
   4. **Credentials.** `CLOGLOG_API_KEY` and `DATABASE_URL` live in different homes — probe each at its real source:
      - `printenv CLOGLOG_API_KEY` in the launcher shell. If the repo has `project_id` in `.cloglog/config.yaml` (bootstrapped), the key should live in `~/.cloglog/credentials.d/<project_slug>`; legacy repos without `project_id` fall back to `~/.cloglog/credentials`. Run `grep '^project_id:' <worktree>/.cloglog/config.yaml` to determine which applies. The project API key MUST NOT live in `<worktree>/.env`; `tests/test_mcp_json_no_secret.py` and `.cloglog/on-worktree-create.sh` pin that invariant. If the operator following this checklist is tempted to add the key to `.env`, that is the regression — fix the env or the credentials file instead.
      - `grep '^DATABASE_URL=' <worktree>/.env` — the per-worktree DB URL is what `on-worktree-create.sh` writes; absent ⇒ half-applied bootstrap.
   5. `head -3 <worktree>/.cloglog/launch.sh` — first line is `#!/bin/bash`? Sanity check the file rendered at all.

   The main agent must NOT proceed to the "wait for review/merge" loop until either the `agent_started` event arrives (late-confirmation is fine — log it and continue) OR the operator has explicitly acted (relaunch, abort, or fix-and-retry instruction in the inbox). Treat the launch as failed in the summary table until then.

4. **Present a summary table** to the user showing:

   | Tab Name | Task/Feature | Title | Priority | Status |
   |----------|-------------|-------|----------|--------|
   | wt-... | T-45 | Fix bug in... | high | live (worktree_id `…`) |
   | wt-... | F-12 | Add search... | medium | LAUNCH FAILED — no agent_started in 90s |

## Rules

- **Never skip the git status check.** This is the #1 cause of agent confusion.
- **Always use absolute paths** for AGENT_PROMPT.md references.
- **Tab names must use `wt-*` pattern** for cleanup scripts and reconciliation to work.
- **Only close tabs you created** — never close tabs that were there before.
- **Sequential launch only** — worktrees share git state and must be created one at a time.
- **Board update is mandatory** — every launched agent must have its task tracked on the board.

## Gotchas

### Worktrees branch from `origin/main`, never `HEAD`

A worktree created from a stale local `main` will show phantom diffs
relative to `origin/main` and trip the demo classifier, PR-body drafting,
or any diff-based check. Always `git fetch origin` and create the worktree
off `origin/main` (or `git merge --ff-only origin/main` first).

### Worktree env propagation across `/clear`

`/clear` re-execs the agent in the same zellij tab, which re-invokes
`bash`. Whether the operator's RC-file env (`GH_APP_ID`,
`GH_APP_INSTALLATION_ID`, etc.) survives that re-invocation is host-specific
(DE / login-shell / RC ordering), and silent flakes have shipped where
`gh-app-token.py` exited with `Error: GH_APP_ID environment variable is
required` mid-task. Two-pronged defence (T-348): (a) `gh-app-token.py`
resolves App ID / Installation ID itself from env → `.cloglog/local.yaml` →
`.cloglog/config.yaml`, so non-worktree callers (close-wave, reconcile,
init Step 6c) work without env priming; (b) `launch.sh`'s heredoc still
exports them into the worktree-agent shell so downstream `gh` calls that
read the env directly keep working across `/clear`.

Per-operator identifiers (App ID + Installation ID) live in gitignored
`.cloglog/local.yaml`, never in tracked `.cloglog/config.yaml` — committing
them would point other clones at the wrong installation. Same constraint
applies to any future per-operator value (PEM path overrides,
host-specific webhook tunnel names, etc.).

**Pin:** `tests/plugins/test_launch_skill_exports_gh_app_env.py`
