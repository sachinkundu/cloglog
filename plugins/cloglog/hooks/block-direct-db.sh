#!/bin/bash
# PreToolUse hook — block direct psql / pg_dump / DB access against the
# cloglog dev or prod database from any agent session (T-417).
#
# Background:
#   The "No psql for board lookups" feedback memory keeps getting
#   violated. Even read-only SELECTs bypass the audit log and normalise
#   workflow drift around MCP. Writes are worse. Memory alone hasn't
#   held; this hook turns the rule into an enforced invariant.
#
# Surface covered (per shell statement — see "Statement scoping" below):
#   - psql ... cloglog_(dev|prod)              (board DB connection target)
#   - psql -U cloglog (no -d postgres)         (default-DB form — POSTGRES_DB=cloglog)
#   - pg_dump ... cloglog(_dev|_prod)?         (read access to board DB)
#   - docker (compose )?exec ... psql ...      (containerised entry)
#   - docker (compose )?exec ... pg_dump ...   (containerised dump)
#   - make db-refresh-from-prod                (Makefile wrapper that
#                                               internally hits both DBs)
#
# Admin-DB allowlist (statement-scoped):
#   A statement that explicitly targets the `postgres` maintenance DB
#   (via `-d postgres`, `--dbname postgres`, or a postgresql URI ending
#   in `/postgres`) is allowed even when it authenticates as user
#   `cloglog`. The Makefile's `dev-env` and `db-refresh-from-prod`
#   recipes rely on this shape to bootstrap/drop databases.
#
# Statement scoping (T-417 codex round 3):
#   The allowlist applies PER STATEMENT, not across the whole command.
#   Otherwise `psql -d postgres ...; psql -d cloglog_dev ...` would
#   slip through by leading with an allowed admin call. The hook
#   splits COMMAND_FLAT on `;`, `&&`, `||`, and `|` boundaries and
#   evaluates each statement independently. Any single statement
#   triggering a block pattern (without its own admin allowlist match)
#   rejects the whole command.
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

# --- Wrapper Makefile target — checked at the whole-command level -----
# Wrappers don't fit the statement model (the outer command is `make`,
# the dangerous psql/pg_dump runs inside the recipe). The wrapper itself
# must be blocked even if the command line has unrelated trailing work.
if echo "$COMMAND_FLAT" | grep -qE '\<make\>[^;&|]*\<db-refresh-from-prod\>'; then
  BLOCKED_REASON="wrapper Makefile target db-refresh-from-prod"
  REJECT=1
fi

# --- Statement-scoped checks ------------------------------------------
# Split on `;`, `&&`, `||`, `|` — pipelines count too, since `psql ...
# | grep ...` still opens the forbidden session.  `tr` collapses each
# separator char to a newline; `&&` / `||` become two newlines but that
# only produces empty statements which the loop skips.
STMT_BLOCK_PAT='\<psql\>[^[:space:]].*'  # placeholder, real patterns below

# Per-statement block patterns. Each fires when the connection target
# is the cloglog board DB. The admin allowlist (-d postgres) skips
# rejection within the SAME statement only.
PSQL_DB_PAT='\<psql\>.*\<cloglog_(dev|prod)\>'
PSQL_USER_PAT='\<psql\>.*-U[[:space:]]+cloglog\>'
PGDUMP_PAT='\<pg_dump\>.*\<cloglog(_dev|_prod)?\>'
DOCKER_PSQL_PAT='\<docker\>([[:space:]]+compose)?[[:space:]]+exec\>.*\<psql\>.*\<cloglog'
DOCKER_PGDUMP_PAT='\<docker\>([[:space:]]+compose)?[[:space:]]+exec\>.*\<pg_dump\>.*\<cloglog'
POSTGRES_DB_PAT='(-d[[:space:]]+postgres\>|--dbname[[:space:]]+postgres\>|--dbname=postgres\>|postgresql://[^[:space:]]*/postgres(\>|[[:space:]?]))'

REJECT="${REJECT:-0}"

# IFS newline so the for-loop walks statements verbatim (preserves
# embedded spaces). Old IFS restored after the loop.
OLD_IFS="$IFS"
IFS=$'\n'
for stmt in $(printf '%s' "$COMMAND_FLAT" | tr ';|&' '\n'); do
  # Trim leading/trailing whitespace; skip empty statements (produced
  # by `&&` / `||` decomposing to two adjacent separators).
  stmt_trim=$(echo "$stmt" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
  [[ -z "$stmt_trim" ]] && continue

  # Per-statement admin allowlist: -d postgres anywhere in THIS
  # statement means it targets the maintenance DB.
  if echo "$stmt_trim" | grep -qE "$POSTGRES_DB_PAT"; then
    continue
  fi

  if echo "$stmt_trim" | grep -qE "$PSQL_DB_PAT" \
     || echo "$stmt_trim" | grep -qE "$PSQL_USER_PAT" \
     || echo "$stmt_trim" | grep -qE "$PGDUMP_PAT" \
     || echo "$stmt_trim" | grep -qE "$DOCKER_PSQL_PAT" \
     || echo "$stmt_trim" | grep -qE "$DOCKER_PGDUMP_PAT"; then
    REJECT=1
    BLOCKED_REASON="${BLOCKED_REASON:-direct psql / pg_dump against cloglog DB}"
    break
  fi
done
IFS="$OLD_IFS"

if [[ "$REJECT" == "1" ]]; then
  cat >&2 <<EOF
Blocked: ${BLOCKED_REASON}.

Direct psql / pg_dump access to the cloglog dev or prod database is
prohibited.  Use MCP tools for board state — every shortcut around
MCP weakens the product premise (cloglog *is* the multi-agent infra;
raw-DB access from any agent is exactly what MCP replaces).

Common alternatives:
  - Lookup by number (T-NNN / F-NN / E-N) → mcp__cloglog__search(query: "T-228")
  - Free-text entity lookup               → mcp__cloglog__search(query: "...")
  - Board state                           → mcp__cloglog__get_board
                                            mcp__cloglog__list_epics
                                            mcp__cloglog__list_features
  - Non-done tasks                        → mcp__cloglog__get_active_tasks
  - Full hierarchy                        → mcp__cloglog__get_backlog

Escape hatch (rare schema audits only): prefix with \`ALLOW_RAW_DB=1 ...\`.
If you find yourself reaching for it, file a task to add the missing
MCP tool first.
EOF
  exit 2
fi

exit 0
