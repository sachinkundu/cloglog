#!/bin/bash
# PreToolUse hook — block direct psql / pg_dump / DB access against the
# cloglog dev or prod database (or the default `cloglog` board DB) from
# any agent session (T-417).
#
# Background:
#   The "No psql for board lookups" feedback memory keeps getting
#   violated. Even read-only SELECTs bypass the audit log and normalise
#   workflow drift around MCP. Writes are worse. Memory alone hasn't
#   held; this hook turns the rule into an enforced invariant.
#
# Protected DBs:
#   cloglog        (docker-compose.yml default POSTGRES_DB)
#   cloglog_dev    (host dev DB)
#   cloglog_prod   (host prod DB)
#
# Triggers (any of these inside a single statement → block):
#   - explicit DB target — `-d cloglog{,_dev,_prod}`, `--dbname[= ]cloglog…`,
#     or a `postgresql://.../cloglog…` URI.
#   - cloglog user — `-U cloglog` or `--username[= ]cloglog`. POSTGRES_DB
#     defaults to the user name, so a connection as user `cloglog` with
#     no other DB hint lands on the `cloglog` board DB.
#   - libpq env prefixes — `PGDATABASE=cloglog{,_dev,_prod}` or
#     `PGUSER=cloglog` on the same statement as a psql/pg_dump call.
#     Codex round 4 caught these as silent bypasses.
#   - covered tools — `psql`, `pg_dump`, and `docker (compose )?exec …
#     (psql|pg_dump) …`. The docker form captures the project's normal
#     container-side access (Makefile `dev-env`, `db-refresh-from-prod`).
#   - wrapper Makefile target — `make db-refresh-from-prod` is blocked
#     by name (the recipe internally hits both DBs, but the outer
#     command is `make ...`).
#
# Admin-DB allowlist (statement-scoped, T-417 codex round 3):
#   A statement that explicitly targets the `postgres` maintenance DB
#   via `-d postgres`, `--dbname[= ]postgres`, or `postgresql://.../postgres`
#   is allowed even when it authenticates as user `cloglog` or mentions
#   cloglog_(dev|prod) in a SQL literal. The Makefile's `dev-env` and
#   `db-refresh-from-prod` recipes rely on this shape to bootstrap/drop
#   databases.
#
# Statement scoping (T-417 codex round 3):
#   The hook splits the command on `;`, `&&`, `||`, `|` and evaluates
#   each statement independently. The admin allowlist suppresses
#   rejection only within the statement that carries `-d postgres`, so
#   `psql -d postgres ...; psql -d cloglog_dev ...` is still rejected.
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
if echo "$COMMAND_FLAT" | grep -qE '(^|[[:space:];&|(])ALLOW_RAW_DB=1(\b|[[:space:]])'; then
  exit 0
fi

# --- Wrapper Makefile target — checked at the whole-command level -----
# Wrappers don't fit the statement model (the outer command is `make`,
# the dangerous psql/pg_dump runs inside the recipe).
if echo "$COMMAND_FLAT" | grep -qE '\<make\>[^;&|]*\<db-refresh-from-prod\>'; then
  BLOCKED_REASON="wrapper Makefile target db-refresh-from-prod"
  REJECT=1
fi

# --- Per-statement triggers -------------------------------------------
# Protected DB names — bare cloglog matches the default POSTGRES_DB; the
# `_(dev|prod)` suffix is optional. `\<…\>` keeps `cloglog_other` from
# matching `\<cloglog\>` (underscore is a word char in grep -E).
PROTECTED_DB='cloglog(_(dev|prod))?'

# Explicit DB-target spellings: `-d <db>`, `--dbname <db>`, `--dbname=<db>`,
# or a postgresql URI ending in `/<db>` (optionally followed by a query
# string).
DB_TARGET_PAT="(-d[[:space:]]+${PROTECTED_DB}\\>|--dbname[[:space:]]+${PROTECTED_DB}\\>|--dbname=${PROTECTED_DB}\\>|postgresql://[^[:space:]]*/${PROTECTED_DB}(\\>|[[:space:]?]))"

# Cloglog-user spellings: `-U cloglog`, `--username cloglog`,
# `--username=cloglog`. Round 4 caught the long forms as bypasses.
USER_PAT='(-U[[:space:]]+cloglog\>|--username[[:space:]]+cloglog\>|--username=cloglog\>)'

# libpq env prefixes — block when the env var names a protected DB or
# user.  Round 4 caught these as silent bypasses (the regex was only
# inspecting args after the psql token).
ENV_DB_PAT="(^|[[:space:];&|(])PGDATABASE=${PROTECTED_DB}(\\>|[[:space:]])"
ENV_USER_PAT='(^|[[:space:];&|(])PGUSER=cloglog(\>|[[:space:]])'

# Admin-DB allowlist (statement-scoped). Same shapes as DB_TARGET_PAT
# but for the `postgres` maintenance DB.
POSTGRES_DB_PAT='(-d[[:space:]]+postgres\>|--dbname[[:space:]]+postgres\>|--dbname=postgres\>|postgresql://[^[:space:]]*/postgres(\>|[[:space:]?]))'

REJECT="${REJECT:-0}"

OLD_IFS="$IFS"
IFS=$'\n'
for stmt in $(printf '%s' "$COMMAND_FLAT" | tr ';|&' '\n'); do
  stmt_trim=$(echo "$stmt" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
  [[ -z "$stmt_trim" ]] && continue

  # Per-statement admin allowlist — explicit -d postgres anywhere in
  # this statement means it targets the maintenance DB.
  if echo "$stmt_trim" | grep -qE "$POSTGRES_DB_PAT"; then
    continue
  fi

  # Is this statement about psql / pg_dump (host or docker exec)?
  is_psql=0
  is_pgdump=0
  echo "$stmt_trim" | grep -qE '\<psql\>' && is_psql=1
  echo "$stmt_trim" | grep -qE '\<pg_dump\>' && is_pgdump=1
  [[ "$is_psql" == "1" || "$is_pgdump" == "1" ]] || continue

  # Does this statement carry any block trigger?
  if echo "$stmt_trim" | grep -qE "$DB_TARGET_PAT" \
     || echo "$stmt_trim" | grep -qE "$USER_PAT" \
     || echo "$stmt_trim" | grep -qE "$ENV_DB_PAT" \
     || echo "$stmt_trim" | grep -qE "$ENV_USER_PAT"; then
    REJECT=1
    if [[ "$is_pgdump" == "1" ]]; then
      BLOCKED_REASON="${BLOCKED_REASON:-direct pg_dump against cloglog DB}"
    else
      BLOCKED_REASON="${BLOCKED_REASON:-direct psql against cloglog DB}"
    fi
    break
  fi
done
IFS="$OLD_IFS"

if [[ "$REJECT" == "1" ]]; then
  cat >&2 <<EOF
Blocked: ${BLOCKED_REASON}.

Direct psql / pg_dump access to the cloglog dev / prod / default
databases is prohibited.  Use MCP tools for board state — every
shortcut around MCP weakens the product premise (cloglog *is* the
multi-agent infra; raw-DB access from any agent is exactly what MCP
replaces).

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
