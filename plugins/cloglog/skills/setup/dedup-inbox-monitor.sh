#!/usr/bin/env bash
# Process-level inbox-monitor deduplication for the setup SKILL.
#
# Every Claude session creates a new task registry, so TaskList cannot detect
# tail processes spawned in prior sessions — they become invisible orphans that
# duplicate every inbox event. This script finds them via `ps` (which sees all
# host processes) and reduces the running tail count to exactly zero or one.
#
# Usage:
#   bash dedup-inbox-monitor.sh <inbox_absolute_path>
#
# Exit codes:
#   0  — exactly one tail monitor remains; caller must NOT spawn a new Monitor.
#   2  — no live monitor (any orphan was killed); caller must spawn a fresh Monitor.
#
# Two monitor forms are detected (mirrors enforce-inbox-monitor-after-pr.sh):
#   Canonical: tail -n 0 -F <absolute_inbox_path>  — matched via $NF == inbox
#   Legacy:    tail -n 0 -F .cloglog/inbox          — matched via /proc/<pid>/cwd
#
# Cross-project safety:
#   Canonical form: `$NF == inbox` is exact string equality, so other projects'
#     inbox paths never match.
#   Legacy form: /proc/<pid>/cwd must equal the inbox owner directory
#     (dirname dirname inbox), so a legacy tail from an unrelated checkout is
#     not treated as this project's monitor.

set -euo pipefail

INBOX="${1:?usage: dedup-inbox-monitor.sh <inbox_absolute_path>}"

# The owning directory for a legacy-form cwd check: parent of .cloglog/.
# e.g. /home/user/cloglog/.cloglog/inbox  →  /home/user/cloglog
EXPECTED_CWD="$(dirname "$(dirname "$INBOX")")"

# ── helper: collect all candidate tail PIDs ───────────────────────────────
_collect_pids() {
  local -a found=()

  # 1. Canonical form: `tail ... <absolute-inbox-path>` — last argv == inbox.
  #    Field 2 must be "tail" or end with "/tail" to exclude bash wrappers
  #    whose command line happens to contain the inbox path (e.g. the Claude
  #    harness shell snapshot that spawned the Monitor).
  while IFS= read -r pid; do
    [[ -n "$pid" ]] && found+=("$pid")
  done < <(
    ps -ww -eo pid=,args= 2>/dev/null \
      | awk -v inbox="$INBOX" '$2 ~ /\/tail$|^tail$/ && $NF == inbox {print $1}' \
    || true
  )

  # 2. Legacy form: `tail ... .cloglog/inbox` (relative path).
  #    The setup and github-bot SKILLs document this as a supported form for
  #    dedupe and crash-recovery flows; the enforce-inbox-monitor hook already
  #    handles it via /proc/<pid>/cwd and we must too or we'll miss orphans
  #    from prior sessions that used the relative form (T-419 codex finding).
  if [[ -d "/proc/1" ]]; then
    while IFS= read -r line; do
      local pid
      pid=$(printf '%s' "$line" | awk '{print $1}')
      [[ "$pid" =~ ^[0-9]+$ ]] || continue
      local proc_cwd
      proc_cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null) || continue
      if [[ "$proc_cwd" == "$EXPECTED_CWD" ]]; then
        found+=("$pid")
      fi
    done < <(
      ps -ww -eo pid=,args= 2>/dev/null \
        | grep -E '[[:space:]]tail[[:print:]]* \.cloglog/inbox$' \
      || true
    )
  else
    # Non-Linux (/proc unavailable): cwd cannot be verified for relative-form
    # monitors.  Accepting them unconditionally is cross-project unsafe — two
    # cloglog checkouts on the same macOS host would each match the other's
    # legacy tail and could kill a monitor that belongs to the other project.
    # Emit a diagnostic and skip the legacy scan; the canonical-form scan
    # (absolute path) is still cross-project safe and covers the common case.
    echo "WARNING: /proc not available; skipping legacy relative-path monitor scan. Legacy 'tail .cloglog/inbox' orphans from prior sessions will not be detected on this host." >&2
  fi

  # Deduplicate (a canonical + legacy match on the same PID is counted once).
  local -A seen=()
  for pid in "${found[@]}"; do
    if [[ -z "${seen[$pid]+_}" ]]; then
      seen[$pid]=1
      printf '%s\n' "$pid"
    fi
  done
}

# ── collect all matching PIDs ─────────────────────────────────────────────
mapfile -t pids < <(_collect_pids)

n=${#pids[@]}

# ── branch on count ───────────────────────────────────────────────────────
if [[ $n -eq 0 ]]; then
  # No monitor running — caller must spawn fresh.
  exit 2

elif [[ $n -eq 1 ]]; then
  # One orphan from a prior session.  Kill it and respawn so the new Monitor()
  # call is bound to this conversation's task registry (T-419 option a).
  kill "${pids[0]}" 2>/dev/null || true
  echo "Killed orphan tail PID ${pids[0]} on ${INBOX}; spawning fresh monitor." >&2
  exit 2

else
  # Multiple duplicates. Keep the oldest (highest elapsed seconds), kill the rest.
  oldest_pid=""
  max_elapsed=-1
  for pid in "${pids[@]}"; do
    elapsed=$(ps -p "$pid" -o etimes= 2>/dev/null | tr -d '[:space:]') || continue
    if [[ -n "$elapsed" && "$elapsed" -gt "$max_elapsed" ]]; then
      max_elapsed="$elapsed"
      oldest_pid="$pid"
    fi
  done

  # Fallback: if ps elapsed-time lookup failed for all (race), keep the first.
  if [[ -z "$oldest_pid" ]]; then
    oldest_pid="${pids[0]}"
  fi

  killed=0
  for pid in "${pids[@]}"; do
    if [[ "$pid" != "$oldest_pid" ]]; then
      kill "$pid" 2>/dev/null && (( killed++ )) || true
    fi
  done
  echo "Killed ${killed} duplicate tail(s); keeping PID ${oldest_pid} on ${INBOX}." >&2
  exit 0
fi
