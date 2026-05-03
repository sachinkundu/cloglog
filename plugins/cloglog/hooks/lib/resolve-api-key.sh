#!/bin/bash
# T-382 — shared CLOGLOG_API_KEY resolver for plugin hooks.
#
# Resolution order matches mcp-server/src/credentials.ts loadApiKey and the
# launch SKILL `_api_key` helper:
#   1. CLOGLOG_API_KEY env (operator override)
#   2. ~/.cloglog/credentials.d/<project_slug>  (per-project)
#   3. ~/.cloglog/credentials                   (legacy global)
#
# The slug derives from the located config.yaml's `project:` scalar, with
# `basename($PROJECT_ROOT)` as fallback. Both candidates are validated
# against [A-Za-z0-9._-]+ to refuse path traversal — anything else is
# treated as no slug, and the resolver falls through to the legacy file.
#
# Why this lives here: the SessionEnd unregister hook
# (plugins/cloglog/hooks/agent-shutdown.sh) and the WorktreeCreate
# registration hook (plugins/cloglog/hooks/worktree-create.sh) both run
# with the system bash, before any agent-side state is built. Without
# per-project resolution they'd send the wrong project's key on a
# multi-project host and earn silent 401/403 — leaving the worktree
# half-registered (worktree-create) or skipping the unregister POST
# entirely (agent-shutdown). The launch SKILL inlines the same logic
# because launch.sh is heredoc-rendered standalone and cannot source
# from the plugin tree.

# resolve_api_key_slug <config-path>
#   Echoes the project slug for credentials.d/<slug> lookup. Empty on miss.
resolve_api_key_slug() {
  local cfg="$1"
  local re='^[A-Za-z0-9._-]+$'
  local slug=""
  if [[ -n "$cfg" && -f "$cfg" ]]; then
    slug=$(grep '^project:' "$cfg" 2>/dev/null | head -n1 \
            | sed 's/^project:[[:space:]]*//' \
            | sed 's/[[:space:]]*#.*$//' \
            | tr -d '"'"'")
  fi
  if [[ -n "$slug" && "$slug" =~ $re ]]; then
    printf '%s\n' "$slug"
    return
  fi
  if [[ -n "$cfg" ]]; then
    local proj_root
    proj_root=$(dirname "$(dirname "$cfg")")
    slug=$(basename "$proj_root")
    if [[ -n "$slug" && "$slug" =~ $re ]]; then
      printf '%s\n' "$slug"
    fi
  fi
}

# _resolve_api_key_read <credentials-file-path>
#   Internal: parse a KEY=VALUE credentials file and echo the
#   CLOGLOG_API_KEY value, stripping surrounding quotes. Empty on miss.
_resolve_api_key_read() {
  local cred="$1"
  [[ -r "$cred" ]] || return 0
  grep -E '^CLOGLOG_API_KEY=' "$cred" 2>/dev/null | head -n1 | cut -d= -f2- | tr -d '"'"'" || true
}

# resolve_api_key <config-path>
#   Echoes the resolved API key (or empty on miss). config-path is the
#   project's .cloglog/config.yaml — used to derive the slug for the
#   per-project lookup.
resolve_api_key() {
  local cfg="$1"
  local key="${CLOGLOG_API_KEY:-}"
  if [[ -n "$key" ]]; then
    printf '%s\n' "$key"
    return
  fi
  local slug
  slug=$(resolve_api_key_slug "$cfg")
  if [[ -n "$slug" ]]; then
    key=$(_resolve_api_key_read "${HOME}/.cloglog/credentials.d/${slug}")
    if [[ -n "$key" ]]; then
      printf '%s\n' "$key"
      return
    fi
  fi
  _resolve_api_key_read "${HOME}/.cloglog/credentials"
}
