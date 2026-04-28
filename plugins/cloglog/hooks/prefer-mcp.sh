#!/bin/bash
# PreToolUse hook — block direct HTTP to the cloglog backend API.
# Rule surface: ${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md §4 (MCP discipline).
#
# T-219: two bypass holes in the original hook are closed here.
#   (1) Host-name bypass — the earlier hook only matched ${BACKEND_HOST}
#       verbatim, so `localhost:8001` / `0.0.0.0:8001` / `[::1]:8001`
#       slipped past. We now block the full loopback alias set plus any
#       optional tunnel host declared in config.yaml.
#   (2) Keyword allowlist — `test|debug|verify|check.*status` anywhere
#       in the command let the curl through, which is trivially spoofable
#       by adding `# debug` to the line. Replaced with an explicit env
#       prefix `CLOGLOG_ALLOW_DIRECT_API=1` that demo tooling must set
#       intentionally. Documentation only: `man prefer-mcp.sh` doesn't
#       exist, so if you're reading this comment because a legitimate
#       demo script is being blocked, the fix is to prefix the command
#       with `CLOGLOG_ALLOW_DIRECT_API=1 ...` inline.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd')

# Only check Bash tool calls.
[[ "$TOOL_NAME" == "Bash" ]] || exit 0
[[ -n "$COMMAND" ]] || exit 0

# Flatten newlines so grep can span multi-line heredocs / python -c blocks.
COMMAND_FLAT=$(printf '%s' "$COMMAND" | tr '\n' ' ')

# --- Escape hatch ---------------------------------------------------------
# Inline env prefix only — `export CLOGLOG_ALLOW_DIRECT_API=1` from a prior
# Bash tool call does NOT carry over (each call is a fresh shell). Demo and
# showboat scripts that need direct backend access must prefix the command
# itself, e.g.:
#   CLOGLOG_ALLOW_DIRECT_API=1 uvx showboat exec ... 'curl -sf "$BASE/..."'
if echo "$COMMAND_FLAT" | grep -qE '(^|[[:space:];&|(])CLOGLOG_ALLOW_DIRECT_API=1(\b|[[:space:]])'; then
  exit 0
fi

# --- Find config ----------------------------------------------------------
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

CONFIG=$(find_config "$CWD") || exit 0

# --- Parse backend host + optional tunnel host ---------------------------
# grep/sed instead of python/yaml: system python3 often lacks pyyaml (that
# module lives in the uv-managed venv, not the interpreter the hook runs
# under). Cloglog's config.yaml uses simple top-level `key: value` pairs,
# so a regex-grade parse is both sufficient and more portable.
_read_key() {
  local key="$1"
  grep "^${key}:" "$CONFIG" \
    | head -1 \
    | sed "s/^${key}:[[:space:]]*//" \
    | sed 's/[[:space:]]*#.*$//' \
    | tr -d '"'"'"
}

BACKEND_URL=$(_read_key backend_url)
[[ -n "$BACKEND_URL" ]] || BACKEND_URL="http://localhost:8000"

# Strip scheme to get `host[:port]` — e.g. http://127.0.0.1:8001 → 127.0.0.1:8001.
BACKEND_HOST=$(echo "$BACKEND_URL" | sed 's|https\?://||' | sed 's|/$||')

# Drop the port for the host-alias list so `localhost:8001` and `localhost`
# match the same alternative. We'll match a trailing `:PORT` separately.
BACKEND_HOST_NOPORT=$(echo "$BACKEND_HOST" | sed 's/:[0-9]*$//')

TUNNEL_HOST=$(_read_key tunnel_host)

# Loopback aliases that all resolve to the backend running on the dev host.
# Each alternative below corresponds to a real bypass observed during T-219
# investigation:
#   BACKEND_HOST_NOPORT → whatever backend_url declares (e.g. 127.0.0.1)
#   127.0.0.1           → IPv4 loopback (the canonical form)
#   localhost           → hostname loopback alias
#   0.0.0.0             → bind-all address; works for local clients
#   ::1 / [::1]         → IPv6 loopback (bracketed form in URLs)
#   TUNNEL_HOST         → optional cloudflared hostname (from config)
HOSTS=(
  "$BACKEND_HOST_NOPORT"
  "127.0.0.1"
  "localhost"
  "0.0.0.0"
  "::1"
  "\\[::1\\]"
)
[[ -n "$TUNNEL_HOST" ]] && HOSTS+=("$TUNNEL_HOST")

# Build the alternation, escaping dots so `127.0.0.1` doesn't match
# `127X0X0X1`. Hosts are otherwise regex-metachar-free in practice.
HOST_ALT=""
for h in "${HOSTS[@]}"; do
  [[ -z "$h" ]] && continue
  esc=$(printf '%s' "$h" | sed 's/\./\\./g')
  HOST_ALT="${HOST_ALT:+$HOST_ALT|}$esc"
done

# --- Tool-invocation pattern ---------------------------------------------
# Each alternative matches one network client and is paired with a
# backend-host regex below. Unrelated fetches (e.g. installing uv from
# astral.sh) do not mention any backend host and stay allowed.
#
#   curl                         — GNU curl, most common
#   wget                         — alternate GNU fetcher
#   \<http[[:space:]]+           — httpie CLI; `\<http\>` alone would match
#                                  the string `http://` inside URLs, so we
#                                  require whitespace after `http` (CLI
#                                  form: `http GET ...`) to avoid that.
#   python3? -m http.client      — stdlib one-liner module invocation
#   python3? -c '…urllib|httpx|requests…' — script one-liner imports
#   node -e '…fetch(…)'          — node fetch one-liner
TOOL_PAT='(\<(curl|wget)\>'
TOOL_PAT+='|(^|[[:space:];&|(])http[[:space:]]+'
TOOL_PAT+='|python3?[[:space:]]+-m[[:space:]]+http\.client'
TOOL_PAT+='|python3?[[:space:]]+-c[[:space:]].*(urllib|httpx|requests)'
TOOL_PAT+='|node[[:space:]]+(-e|--eval)[[:space:]].*fetch\('
TOOL_PAT+=')'

# Bound tool-to-URL matching to a single shell statement: `[^;&|]*?`
# prevents a benign `wget foo.tar.gz` earlier in the line from pairing
# with a backend URL in a later `&&`-joined command. Parentheses are
# intentionally NOT in the exclusion set — python one-liners like
# `requests.get("http://…")` have parens between the tool name and the
# URL, and we still want those blocked.
if echo "$COMMAND_FLAT" | grep -qE "${TOOL_PAT}[^;&|]*?(${HOST_ALT})(:[0-9]+)?/api"; then
  echo "Blocked: direct cloglog backend access prohibited." >&2
  echo "  See ${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md §4 (MCP discipline)." >&2
  echo "  Use MCP tools (mcp__cloglog__*) for all board/worktree operations." >&2
  echo "  Legitimate demo-only escape hatch: inline 'CLOGLOG_ALLOW_DIRECT_API=1 ...'" >&2
  exit 2
fi

exit 0
