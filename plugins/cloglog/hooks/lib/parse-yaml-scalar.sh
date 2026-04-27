#!/bin/bash
# Stdlib-only YAML scalar-key reader for plugin hooks.
#
# Why: `python3 -c 'the python YAML lib'` violates docs/invariants.md:76 — the system
# python3 plugin hooks run under typically lacks PyYAML (the project's PyYAML
# lives in the uv venv, not the global python). The previous python snippets
# silently swallowed ImportError and returned defaults, producing wrong-port
# backend calls and broken parsing on portable hosts.
#
# Authoritative precedent: .cloglog/on-worktree-create.sh:88-105 and
# plugins/cloglog/hooks/agent-shutdown.sh:62-74. This file consolidates that
# pattern into a single sourced helper so the 4 scalar-key sites stop drifting.
#
# Scope: TOP-LEVEL SCALAR KEYS ONLY (e.g. backend_url, project_id,
# quality_command). Nested mappings (e.g. worktree_scopes:) are NOT supported
# — see T-313 / Phase 0b for the nested-mapping parser.

# read_yaml_scalar <config-path> <key> [default]
#   Echoes the YAML scalar value for `key`. Strips surrounding quotes and
#   trailing comments. Falls back to `default` when the file is missing or
#   the key has no value. Silent on missing file with no default.
read_yaml_scalar() {
  local cfg="$1"
  local key="$2"
  local default="${3:-}"

  if [[ ! -f "$cfg" ]]; then
    [[ -n "$default" ]] && printf '%s\n' "$default"
    return 0
  fi

  local parsed
  parsed=$(grep "^${key}:" "$cfg" 2>/dev/null | head -n1 \
           | sed "s/^${key}:[[:space:]]*//" \
           | sed 's/[[:space:]]*#.*$//' \
           | tr -d '"'"'")

  if [[ -n "$parsed" ]]; then
    printf '%s\n' "$parsed"
  elif [[ -n "$default" ]]; then
    printf '%s\n' "$default"
  fi
}
