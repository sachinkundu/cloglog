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
#   Sources the canonical scalar reader at lib/parse-yaml-scalar.sh so any
#   future quote-handling fix lands in one place — drift between the two
#   parsers would let a quoted `project: 'beta'` be MCP-resolvable but
#   hook-invisible (the codex round-4 risk).
resolve_api_key_slug() {
  local cfg="$1"
  local re='^[A-Za-z0-9._-]+$'
  # The lib path is co-located with this file; resolve once at first call.
  local _lib_dir
  _lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # shellcheck source=parse-yaml-scalar.sh
  source "${_lib_dir}/parse-yaml-scalar.sh"
  local slug=""
  if [[ -n "$cfg" && -f "$cfg" ]]; then
    slug=$(read_yaml_scalar "$cfg" "project" "")
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
#   Echoes the resolved API key (or empty on miss/refuse). config-path is
#   the project's .cloglog/config.yaml — used to derive the slug for the
#   per-project lookup.
#
#   Fail-loud invariant: once ~/.cloglog/credentials.d/<slug> EXISTS, it
#   must yield a usable key. If it exists but is unreadable, points at a
#   directory, or contains no/empty CLOGLOG_API_KEY, the resolver returns
#   empty AND logs to /tmp/agent-shutdown-debug.log — it does NOT fall
#   through to the legacy global file, because that file may hold a
#   different project's key and silently sending it recreates the bug
#   T-382 was filed to remove. Empty return means the calling hook skips
#   the POST instead of authenticating as the wrong project.
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
    local proj_file="${HOME}/.cloglog/credentials.d/${slug}"
    if [[ -e "$proj_file" ]]; then
      # File exists — refuse to fall back even if it is unusable.
      if [[ ! -r "$proj_file" ]]; then
        echo "[$(date -Iseconds)] resolve_api_key: ${proj_file} exists but is unreadable; refusing legacy fallback (T-382)" \
          >> /tmp/agent-shutdown-debug.log 2>&1 || true
        return
      fi
      if [[ -d "$proj_file" ]]; then
        echo "[$(date -Iseconds)] resolve_api_key: ${proj_file} is a directory; refusing legacy fallback (T-382)" \
          >> /tmp/agent-shutdown-debug.log 2>&1 || true
        return
      fi
      key=$(_resolve_api_key_read "$proj_file")
      if [[ -n "$key" ]]; then
        printf '%s\n' "$key"
        return
      fi
      echo "[$(date -Iseconds)] resolve_api_key: ${proj_file} present but no CLOGLOG_API_KEY; refusing legacy fallback (T-382)" \
        >> /tmp/agent-shutdown-debug.log 2>&1 || true
      return
    fi
  fi
  # Per-project file is genuinely missing — legacy fallback is OK.
  _resolve_api_key_read "${HOME}/.cloglog/credentials"
}
