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

## Workflow override

@@WORKFLOW_OVERRIDE@@
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
# notes / workflow override are free-form multi-line strings — sed's
# replacement-string substitution doesn't handle newlines cleanly, so
# we write each value to a temp file and use sed's `r FILE` + `d` pair
# to replace the whole placeholder line with the file's contents.
# Each placeholder appears on its own line in the heredoc above, which
# makes whole-line replacement safe.
TMP_DESC=$(mktemp)
TMP_SIB=$(mktemp)
TMP_RES=$(mktemp)
TMP_OVR=$(mktemp)
trap 'rm -f "$TMP_DESC" "$TMP_SIB" "$TMP_RES" "$TMP_OVR"' EXIT

printf '%s' "${TASK_DESCRIPTION:-(none)}"   > "$TMP_DESC"
printf '%s' "${SIBLING_WARNINGS:-(none)}"   > "$TMP_SIB"
printf '%s' "${RESIDUAL_NOTES:-(none)}"     > "$TMP_RES"
printf '%s' "${WORKFLOW_OVERRIDE:-(none)}"  > "$TMP_OVR"

# `sed -i -e '/@@TOKEN@@/{r FILE' -e 'd}'` reads FILE in place of the
# matched line, then deletes the placeholder. Two `-e` arguments are
# required because the `r` command extends to end-of-line.
sed -i -e "/@@TASK_DESCRIPTION@@/{r ${TMP_DESC}" -e "d;}" "${WORKTREE_PATH}/task.md"
sed -i -e "/@@SIBLING_WARNINGS@@/{r ${TMP_SIB}"  -e "d;}" "${WORKTREE_PATH}/task.md"
sed -i -e "/@@RESIDUAL_NOTES@@/{r ${TMP_RES}"    -e "d;}" "${WORKTREE_PATH}/task.md"
sed -i -e "/@@WORKFLOW_OVERRIDE@@/{r ${TMP_OVR}" -e "d;}" "${WORKTREE_PATH}/task.md"
```

The agent reads `AGENT_PROMPT.md` first; the template's first section instructs it to read `task.md` for the per-task delta. The launch.sh fallback prompt (`Read ${WORKTREE_PATH}/AGENT_PROMPT.md and begin.`) is unchanged — `task.md` is reached transitively from the template.

### What the template owns vs. what task.md owns

- **Template (`plugins/cloglog/templates/AGENT_PROMPT.md`):** inbox paths (worktree for read, project root for write), MCP preload, stop-on-MCP-failure, standard workflow steps, per-task shutdown sequence, `workflow_override` semantics, continuation-prompt bootstrap, work-log bootstrap. Update this file once and every future agent inherits the change.
- **`task.md`:** task ID / feature ID / worktree ID / paths, task number / title / priority, description, sibling-task warnings, residual TODOs hint, optional `workflow_override` value (`skip_pr` is the only one defined today).

### Override mechanism

A task that needs to deviate from the standard `pr_merged` flow (e.g. docs/research/prototype with no source-code changes) sets `workflow_override: skip_pr` in `task.md`. The template branches on the field — see the template's **Workflow overrides** section. Future overrides slot into the same field; if the list grows past two values, fold the variants out into named template files rather than branching the template further.

## One task per session

Each worktree agent runs exactly one task per session and exits after the PR merges (or after a `skip_pr` standalone task completes). The supervisor sees `agent_unregistered`, runs the relaunch flow below, and either issues the continuation prompt or triggers `cloglog:close-wave`. Plan tasks are the only exception — a plan task immediately starts the following impl task in the same session; the boundary fires when the impl PR merges.

Full per-task shutdown sequence lives in `${CLAUDE_PLUGIN_ROOT}/templates/AGENT_PROMPT.md` under **Per-task shutdown sequence**.

## Continuation Prompt

When the supervisor relaunches the same worktree for task N+1, it issues:

```
Read ${WORKTREE_PATH}/AGENT_PROMPT.md and all shutdown-artifacts/work-log-T-*.md files in ${WORKTREE_PATH}, then begin the next task.
```

The new session reads the template (already on disk in the worktree from the original launch), reads prior work logs, loads MCP tools, **re-registers via `mcp__cloglog__register_agent` to bind the new MCP session** (the previous session's `unregister_agent` cleared its per-process state), then resolves the active task via `get_my_tasks` (the live source of truth — see the template's Standard workflow step 3 for why `task.md` is read for hints but not trusted for the UUID on continuation), and proceeds normally.

**The launch SKILL writes the initial prompt; the supervisor writes continuation prompts.** Continuation sessions reuse `.cloglog/launch.sh` by passing the prompt as `$1` so the TERM/HUP signal trap and `_unregister_fallback` path from the initial launch are preserved.

**Residual: supervisor-side `task.md` rewrite.** The proper fix for the continuation flow is for the supervisor to rewrite `${WORKTREE_PATH}/task.md` for the next task before issuing the continuation prompt — using the same Step 3 rendering shape. That edit lands in the Supervisor Relaunch Flow section, which T-356 currently owns; this PR (T-360) leaves the agent-side `get_my_tasks` defense as the resolver. Do not remove the defense after the rewrite lands — defense in depth.

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
4. **If no backlog tasks remain** → invoke the `cloglog:close-wave` skill for this worktree.

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
# Capture current tab's stable numeric ID before switching away
CURRENT_TAB_ID=$(zellij action current-tab-info 2>&1 | awk '/^id:/ {print $2}')

# Resolve the project root so the launcher can read backend_url and (as a
# fallback) the MCP API key. Falls back to the current repo.
PROJECT_ROOT="$(git rev-parse --show-toplevel)"

# Write task model for launch.sh — update before each relaunch with the next task's model
# TASK_MODEL comes from the task's `model` field resolved in Step 1b (may be empty)
printf '%s\n' "${TASK_MODEL:-}" > "${WORKTREE_PATH}/.cloglog/task-model"

# Write a launcher script — unquoted EOF expands ${WORKTREE_PATH} / ${PROJECT_ROOT}
# at write time, baking the absolute paths in. T-217: we do NOT use `exec claude`
# here. `exec` would replace the bash wrapper with claude, destroying any trap
# installed in this script — and a SIGTERM from close-wave (step 5) would then
# reach only claude, whose SessionEnd hook is best-effort under signal. By
# running claude as a subprocess and wait()ing for it, the TERM/HUP trap below
# fires reliably and we hit /agents/unregister-by-path directly before claude
# is killed. See ${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md §2 and the T-217 experiment
# output (tab-close sends no signal at all; only the kill step does).
cat > "${WORKTREE_PATH}/.cloglog/launch.sh" << EOF
#!/bin/bash
# Auto-generated by the cloglog launch skill. See plugins/cloglog/skills/launch/SKILL.md.
set -u

WORKTREE_PATH="${WORKTREE_PATH}"
PROJECT_ROOT="${PROJECT_ROOT}"

_backend_url() {
  # T-312: stdlib-only grep+sed scalar parse — same shape as the shared helper
  # at plugins/cloglog/hooks/lib/parse-yaml-scalar.sh. Inlined here because
  # launch.sh runs as a standalone bash exec inside the worktree, with no
  # CLAUDE_PLUGIN_ROOT in scope to source the helper from. Do NOT reintroduce
  # the python YAML lib here — the system python3 typically lacks PyYAML and
  # silently returns the default, breaking ports on portable hosts.
  local cfg="\$PROJECT_ROOT/.cloglog/config.yaml"
  local default="http://localhost:8000"
  [[ -f "\$cfg" ]] || { echo "\$default"; return; }
  local parsed
  parsed=\$(grep '^backend_url:' "\$cfg" 2>/dev/null | head -n1 \\
           | sed 's/^backend_url:[[:space:]]*//' \\
           | sed 's/[[:space:]]*#.*\$//' \\
           | tr -d '"' | tr -d "'")
  if [[ -n "\$parsed" ]]; then echo "\$parsed"; else echo "\$default"; fi
}

_read_scalar_yaml() {
  # T-348: read a top-level scalar key from a YAML file via grep+sed.
  # Same shape as _backend_url and parse-yaml-scalar.sh; do NOT reintroduce
  # the python YAML lib here (docs/invariants.md:76 — system python3
  # typically lacks PyYAML and silently returns the default).
  local file="\$1"; local key="\$2"
  [[ -f "\$file" ]] || return 0
  grep "^\${key}:" "\$file" 2>/dev/null | head -n1 \\
    | sed "s/^\${key}:[[:space:]]*//" \\
    | sed 's/[[:space:]]*#.*\$//' \\
    | tr -d '"' | tr -d "'"
}

_gh_app_id() {
  # Resolution order (T-348): env → .cloglog/local.yaml (gitignored,
  # host-local — preferred) → .cloglog/config.yaml (tracked fallback for
  # single-operator repos). Mirrors gh-app-token.py's _resolve precedence
  # exactly so an operator who keeps a temporary env override is honored,
  # not clobbered by stale YAML.
  [[ -n "\${GH_APP_ID:-}" ]] && { echo "\$GH_APP_ID"; return; }
  local v
  v=\$(_read_scalar_yaml "\$PROJECT_ROOT/.cloglog/local.yaml" "gh_app_id")
  [[ -n "\$v" ]] && { echo "\$v"; return; }
  _read_scalar_yaml "\$PROJECT_ROOT/.cloglog/config.yaml" "gh_app_id"
}

_gh_app_installation_id() {
  # See _gh_app_id resolution order above (env first).
  [[ -n "\${GH_APP_INSTALLATION_ID:-}" ]] && { echo "\$GH_APP_INSTALLATION_ID"; return; }
  local v
  v=\$(_read_scalar_yaml "\$PROJECT_ROOT/.cloglog/local.yaml" "gh_app_installation_id")
  [[ -n "\$v" ]] && { echo "\$v"; return; }
  _read_scalar_yaml "\$PROJECT_ROOT/.cloglog/config.yaml" "gh_app_installation_id"
}

_api_key() {
  # Authoritative lookup order matches mcp-server/src/credentials.ts and the
  # T-214 contract in ${CLAUDE_PLUGIN_ROOT}/docs/setup-credentials.md: env first, then
  # ~/.cloglog/credentials (mode 0600). The worktree's .env and the repo's
  # .mcp.json MUST NOT carry the key — tests/test_mcp_json_no_secret.py
  # pins that invariant and .cloglog/on-worktree-create.sh never writes
  # the key to .env.
  [[ -n "\${CLOGLOG_API_KEY:-}" ]] && { echo "\$CLOGLOG_API_KEY"; return; }
  local cred="\${HOME}/.cloglog/credentials"
  if [[ -r "\$cred" ]]; then
    local v
    v=\$(grep '^CLOGLOG_API_KEY=' "\$cred" 2>/dev/null | head -n 1 | cut -d= -f2-)
    # Strip optional surrounding single/double quotes to match
    # credentials.ts loadApiKey behaviour.
    v=\${v%\"}; v=\${v#\"}; v=\${v%\\'}; v=\${v#\\'}
    [[ -n "\$v" ]] && { echo "\$v"; return; }
  fi
  return 0
}

_unregister_fallback() {
  local sig="\${1:-unknown}"
  local url="\$(_backend_url)"
  local key="\$(_api_key)"
  echo "[\$(date -Iseconds)] launch.sh trap fired sig=\$sig worktree=\$WORKTREE_PATH" >> /tmp/agent-shutdown-debug.log
  if [[ -z "\$key" ]]; then
    echo "[\$(date -Iseconds)] launch.sh trap: no API key; skipping unregister POST" >> /tmp/agent-shutdown-debug.log
    return
  fi
  curl -s --max-time 5 -X POST "\${url}/api/v1/agents/unregister-by-path" \\
    -H "Content-Type: application/json" \\
    -H "Authorization: Bearer \${key}" \\
    -d "{\"worktree_path\": \"\${WORKTREE_PATH}\"}" \\
    >> /tmp/agent-shutdown-debug.log 2>&1 || true
}

CLEANUP_DONE=0
_on_signal() {
  local sig="\$1"
  [[ "\$CLEANUP_DONE" == "1" ]] && return
  CLEANUP_DONE=1
  _unregister_fallback "\$sig"
  if [[ -n "\${CLAUDE_PID:-}" ]] && kill -0 "\$CLAUDE_PID" 2>/dev/null; then
    kill -"\$sig" "\$CLAUDE_PID" 2>/dev/null || true
    # Give claude up to 5s to run its own SessionEnd hook before exiting.
    for _ in 1 2 3 4 5; do
      kill -0 "\$CLAUDE_PID" 2>/dev/null || break
      sleep 1
    done
  fi
  exit 0
}
trap '_on_signal TERM' TERM
trap '_on_signal HUP' HUP
trap '_on_signal INT' INT

cd "\$WORKTREE_PATH"
# T-348: export GitHub App identifiers so the github-bot skill's
# gh-app-token.py can mint installation tokens. These survive \`/clear\`
# because launch.sh re-exports them on every (re)launch, instead of
# relying on shell RC inheritance from whatever spawned zellij.
_GH_APP_ID="\$(_gh_app_id)"
_GH_APP_INSTALLATION_ID="\$(_gh_app_installation_id)"
[[ -n "\$_GH_APP_ID" ]] && export GH_APP_ID="\$_GH_APP_ID"
[[ -n "\$_GH_APP_INSTALLATION_ID" ]] && export GH_APP_INSTALLATION_ID="\$_GH_APP_INSTALLATION_ID"
# Read per-task model from .cloglog/task-model — written by the launch skill (T-332).
# The supervisor rewrites this file before each continuation relaunch so the
# correct model is used for every task, not just the initial one.
_MODEL_FLAG=""
_TASK_MODEL=\$(cat "\$WORKTREE_PATH/.cloglog/task-model" 2>/dev/null || true)
[[ -n "\$_TASK_MODEL" ]] && _MODEL_FLAG="--model \$_TASK_MODEL"
# Optional \$1: continuation prompt string from supervisor relaunch.
# When absent, fall back to reading AGENT_PROMPT.md (initial launch).
_CLAUDE_PROMPT="\${1:-Read ${WORKTREE_PATH}/AGENT_PROMPT.md and begin.}"
claude --dangerously-skip-permissions \${_MODEL_FLAG:+\$_MODEL_FLAG} "\$_CLAUDE_PROMPT" &
CLAUDE_PID=\$!
wait "\$CLAUDE_PID"
EOF
chmod +x "${WORKTREE_PATH}/.cloglog/launch.sh"

# new-tab -- <command> starts the command in the tab's initial pane — no write-chars, no list-clients, no pane-id needed
zellij action new-tab --name "${WORKTREE_NAME}" -- bash "${WORKTREE_PATH}/.cloglog/launch.sh"

# Return focus immediately using stable numeric ID (not affected by tab renames or reordering)
zellij action go-to-tab-by-id "${CURRENT_TAB_ID}"
```

> **`launch.sh` is operator-host-specific.** The unquoted heredoc above expands
> `${WORKTREE_PATH}` and `${PROJECT_ROOT}` at *write time*, baking absolute
> paths that are valid only on the current operator's machine into the script.
> The file is gitignored (`.gitignore`) so it is not a tracked source leak —
> but gitignored does **not** mean "safe to copy". Copying `launch.sh` between
> operators or hosts will produce a script that references non-existent paths on
> the target machine. Each host regenerates this file at launch time from its
> own current `WORKTREE_PATH`. Do not commit it, archive it, or hand it to
> another operator as a working artifact.

### 4f. One agent at a time

Wait briefly between each agent launch. Each needs its own zellij tab.

## Step 5: Verification

After all agents are launched:

1. **List tabs** to confirm all were created:
   ```bash
   zellij action query-tab-names
   ```

2. **Present a summary table** to the user showing:

   | Tab Name | Task/Feature | Title | Priority | Status |
   |----------|-------------|-------|----------|--------|
   | wt-... | T-45 | Fix bug in... | high | launched |
   | wt-... | F-12 | Add search... | medium | launched |

## Rules

- **Never skip the git status check.** This is the #1 cause of agent confusion.
- **Always use absolute paths** for AGENT_PROMPT.md references.
- **Tab names must use `wt-*` pattern** for cleanup scripts and reconciliation to work.
- **Only close tabs you created** — never close tabs that were there before.
- **Sequential launch only** — worktrees share git state and must be created one at a time.
- **Board update is mandatory** — every launched agent must have its task tracked on the board.
