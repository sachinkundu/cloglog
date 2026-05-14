#!/bin/bash
# PreToolUse hook — block direct psql / DB access against the cloglog
# dev or prod database from any agent session (T-417).
#
# Background:
#   The "No psql for board lookups" feedback memory keeps getting
#   violated. Even read-only SELECTs bypass the audit log and normalise
#   workflow drift around MCP. Writes are worse. Memory alone hasn't
#   held; this hook turns the rule into an enforced invariant.
#
# Surface covered:
#   - psql ... cloglog_dev  (dev DB connection target)
#   - psql ... cloglog_prod (prod DB connection target)
#   - docker exec ... psql ... cloglog   (containerised entry)
#
# Escape hatch:
#   Inline env prefix `ALLOW_RAW_DB=1 ...` releases the call. Same
#   pattern as prefer-mcp.sh's `CLOGLOG_ALLOW_DIRECT_API=1` — must be
#   set on the command line itself (each Bash tool call is a fresh
#   shell, so exporting earlier does not persist). If you find
#   yourself reaching for ALLOW_RAW_DB=1, file a task to add the
#   missing MCP tool first — see CLAUDE.md "No psql for board lookups".

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

[[ "$TOOL_NAME" == "Bash" ]] || exit 0
[[ -n "$COMMAND" ]] || exit 0

# Flatten newlines so the regex spans multi-line heredocs / pipelines.
COMMAND_FLAT=$(printf '%s' "$COMMAND" | tr '\n' ' ')

# --- Escape hatch -------------------------------------------------------
# Inline only — `export ALLOW_RAW_DB=1` from a prior Bash call does NOT
# carry over (fresh shell per call).
if echo "$COMMAND_FLAT" | grep -qE '(^|[[:space:];&|(])ALLOW_RAW_DB=1(\b|[[:space:]])'; then
  exit 0
fi

# --- Detect psql / docker-exec-psql against the cloglog DB --------------
# Two shapes are blocked:
#   1. A `psql` invocation that names cloglog_dev or cloglog_prod
#      anywhere in the same statement (covers both `psql -d cloglog_dev`
#      and `psql "postgresql://.../cloglog_prod"`).
#   2. A `docker exec ... psql ...` pipeline that names a cloglog DB
#      (covers `docker exec ... psql -U cloglog -d cloglog_dev ...`).
#
# Statement boundary `[^;&|]*` keeps an unrelated earlier command on
# the same line from pairing with a later cloglog reference.
PSQL_DB_PAT='\<psql\>[^;&|]*\<cloglog_(dev|prod)\>'
DOCKER_PSQL_PAT='\<docker[[:space:]]+exec\>[^;&|]*\<psql\>[^;&|]*\<cloglog'

if echo "$COMMAND_FLAT" | grep -qE "$PSQL_DB_PAT" \
   || echo "$COMMAND_FLAT" | grep -qE "$DOCKER_PSQL_PAT"; then
  cat >&2 <<'EOF'
Blocked: direct psql / DB access to the cloglog dev or prod database is prohibited.

Use MCP tools for board state — every shortcut around MCP weakens the
product premise (cloglog *is* the multi-agent infra; raw-DB access
from any agent is exactly what MCP replaces).

Common alternatives:
  - Lookup by number (T-NNN / F-NN / E-N) → mcp__cloglog__search(query: "T-228")
  - Free-text entity lookup               → mcp__cloglog__search(query: "...")
  - Board state                           → mcp__cloglog__get_board
                                            mcp__cloglog__list_epics
                                            mcp__cloglog__list_features
  - Non-done tasks                        → mcp__cloglog__get_active_tasks
  - Full hierarchy                        → mcp__cloglog__get_backlog

Escape hatch (rare schema audits only): prefix with `ALLOW_RAW_DB=1 ...`.
If you find yourself reaching for it, file a task to add the missing
MCP tool first.
EOF
  exit 2
fi

exit 0
