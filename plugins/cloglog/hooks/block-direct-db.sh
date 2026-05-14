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
#   - psql ... cloglog_dev   (dev DB connection target)
#   - psql ... cloglog_prod  (prod DB connection target)
#   - psql -U cloglog        (default-DB form — docker-compose.yml's
#                             POSTGRES_DB is `cloglog`, so a connection
#                             that names the user without an explicit
#                             `-d` lands on the cloglog DB)
#   - docker exec ... psql ... cloglog          (containerised entry)
#   - docker compose exec ... psql ... cloglog  (the project's normal
#                             container-side Postgres access — covered
#                             explicitly because `docker exec` alone
#                             missed this shape (T-417 codex round 1)).
#   - make db-refresh-from-prod                  (Makefile wrapper that
#                             internally pg_dumps cloglog into cloglog_dev
#                             — a shipped bypass of the direct-psql guard
#                             since the outer command is `make ...`, not
#                             `psql ...` (T-417 codex round 2)).
#
# Documented admin commands targeting the `postgres` maintenance DB are
# allowed even when they authenticate as user `cloglog`: the Makefile's
# `dev-env` and `db-refresh-from-prod` recipes run
# `psql -U cloglog -d postgres -c "...DATABASE cloglog_dev..."` to
# bootstrap/drop databases. The `-U cloglog` rule below skips rejection
# when the same statement carries an explicit `-d postgres` / postgresql
# URI to postgres (T-417 codex round 2). The cloglog_(dev|prod) and
# docker-cloglog patterns still fire regardless — those are about the
# destination DB, not the user.
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
# Three shapes are blocked:
#   1. A `psql` invocation that names cloglog_dev or cloglog_prod
#      anywhere in the same statement (covers both `psql -d cloglog_dev`
#      and `psql "postgresql://.../cloglog_prod"`).
#   2. A `psql -U cloglog` invocation with no other DB hint — the
#      docker-compose.yml default `POSTGRES_DB: cloglog` means the
#      connection lands on the cloglog DB even without an explicit
#      `-d`. Matched by the `-U cloglog` flag alone.
#   3. A `docker (compose )?exec ... psql ...` pipeline that names a
#      cloglog DB (covers both `docker exec ... psql -U cloglog
#      -d cloglog_dev ...` and the project's normal `docker compose
#      exec -T postgres psql -U cloglog ...` access pattern from the
#      Makefile).
#
# Statement boundary `[^;&|]*` keeps an unrelated earlier command on
# the same line from pairing with a later cloglog reference.
PSQL_DB_PAT='\<psql\>[^;&|]*\<cloglog_(dev|prod)\>'
PSQL_USER_PAT='\<psql\>[^;&|]*-U[[:space:]]+cloglog\>'
DOCKER_PSQL_PAT='\<docker\>([[:space:]]+compose)?[[:space:]]+exec\>[^;&|]*\<psql\>[^;&|]*\<cloglog'
MAKE_WRAPPER_PAT='\<make\>[^;&|]*\<db-refresh-from-prod\>'
# Admin-DB allowlist: a statement that explicitly targets the `postgres`
# maintenance DB (via `-d postgres`, `--dbname postgres`, or a
# postgresql URI ending in `/postgres`) is allowed even when it
# authenticates as user `cloglog` — those are bootstrap/admin commands,
# not board-DB access.
POSTGRES_DB_PAT='(-d[[:space:]]+postgres\>|--dbname[[:space:]]+postgres\>|--dbname=postgres\>|postgresql://[^[:space:]]*/postgres(\>|[[:space:]?]))'

# Wrapper Makefile target — match before the psql/docker regex block.
# (The wrapper recipe internally pg_dumps cloglog into cloglog_dev; the
# `-d postgres` admin skip below does NOT apply because the recipe also
# runs board-DB-targeted psql lines.)
if echo "$COMMAND_FLAT" | grep -qE "$MAKE_WRAPPER_PAT"; then
  : # fall through to the block message below
elif echo "$COMMAND_FLAT" | grep -qE "$POSTGRES_DB_PAT"; then
  # Explicit `-d postgres` admin command — allowed even when it
  # authenticates as user `cloglog` or mentions cloglog_dev/prod in
  # a SQL literal. The connection target is the maintenance DB, which
  # has no access to board tables.
  exit 0
elif echo "$COMMAND_FLAT" | grep -qE "$PSQL_DB_PAT"; then
  :
elif echo "$COMMAND_FLAT" | grep -qE "$PSQL_USER_PAT"; then
  :
elif echo "$COMMAND_FLAT" | grep -qE "$DOCKER_PSQL_PAT"; then
  :
else
  exit 0
fi

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

exit 0
