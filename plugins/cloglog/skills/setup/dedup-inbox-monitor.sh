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
#   2  — always; all orphans/duplicates were killed; caller MUST spawn a fresh Monitor.
#         (exit 0 was removed: keeping an orphan leaves no Monitor task bound to the
#          current session, so webhook events never surface as notifications.)
#
# Two monitor forms are detected (mirrors enforce-inbox-monitor-after-pr.sh):
#   Canonical: tail -n 0 -F <absolute_inbox_path>  — matched via $NF == inbox
#   Legacy:    tail -n 0 -F .cloglog/inbox          — matched via cwd lookup
#
# cwd lookup strategy (cross-project safety for legacy form):
#   Linux:   /proc/<pid>/cwd  (always available)
#   Other:   lsof -a -p <pid> -d cwd -Fn (requires lsof, default on macOS)
#   Neither: legacy scan skipped; canonical form still deduped correctly.
#
# Bash 3.2 compatible (no mapfile, no local -A).

set -euo pipefail

INBOX="${1:?usage: dedup-inbox-monitor.sh <inbox_absolute_path>}"

# The owning directory for a legacy-form cwd check: parent of .cloglog/.
# e.g. /home/user/cloglog/.cloglog/inbox  →  /home/user/cloglog
EXPECTED_CWD="$(dirname "$(dirname "$INBOX")")"

# ── portable cwd lookup ───────────────────────────────────────────────────
# Outputs the resolved cwd for a given PID, or nothing on failure.
_get_proc_cwd() {
  local pid="$1"
  if [[ -d "/proc/1" ]]; then
    readlink -f "/proc/$pid/cwd" 2>/dev/null || true
  elif command -v lsof >/dev/null 2>&1; then
    lsof -a -p "$pid" -d cwd -Fn 2>/dev/null \
      | grep '^n' | sed 's/^n//' | head -1 || true
  fi
}

# ── collect all candidate tail PIDs ──────────────────────────────────────
# Outputs one PID per line, deduplicated.
_collect_pids() {
  # Collect into a plain newline-separated string to avoid Bash 4-isms.
  local raw=""

  # 1. Canonical form: `tail ... <absolute-inbox-path>` — last argv == inbox.
  #    Field 2 must be "tail" or end with "/tail" to exclude bash wrappers
  #    whose command line happens to contain the inbox path.
  local canonical
  canonical=$(
    ps -ww -eo pid=,args= 2>/dev/null \
      | awk -v inbox="$INBOX" '$2 ~ /\/tail$|^tail$/ && $NF == inbox {print $1}' \
    || true
  )
  [[ -n "$canonical" ]] && raw="${raw}${canonical}"$'\n'

  # 2. Legacy form: `tail ... .cloglog/inbox` (relative path).
  #    The setup and github-bot SKILLs document this as a supported form.
  #    We verify cwd so that tails from unrelated checkouts are excluded.
  local legacy_candidates
  legacy_candidates=$(
    ps -ww -eo pid=,args= 2>/dev/null \
      | grep -E '[[:space:]]tail[[:print:]]* \.cloglog/inbox$' \
      | awk '{print $1}' \
    || true
  )

  if [[ -n "$legacy_candidates" ]]; then
    local have_cwd_tool=0
    [[ -d "/proc/1" ]] && have_cwd_tool=1
    ! ((have_cwd_tool)) && command -v lsof >/dev/null 2>&1 && have_cwd_tool=1

    if ((have_cwd_tool)); then
      local pid proc_cwd
      while IFS= read -r pid; do
        [[ -n "$pid" ]] || continue
        proc_cwd=$(_get_proc_cwd "$pid")
        if [[ "$proc_cwd" == "$EXPECTED_CWD" ]]; then
          raw="${raw}${pid}"$'\n'
        fi
      done <<< "$legacy_candidates"
    else
      echo "WARNING: /proc and lsof unavailable; legacy relative-path monitors cannot be deduped on this host." >&2
    fi
  fi

  # Deduplicate via awk (Bash 3.2 compatible — no associative arrays needed).
  printf '%s' "$raw" | awk 'NF && !seen[$0]++'
}

# ── collect all matching PIDs ─────────────────────────────────────────────
# Use while-read loop (Bash 3.2 compatible; mapfile requires Bash 4+).
pids=()
while IFS= read -r pid; do
  [[ -n "$pid" ]] && pids+=("$pid")
done < <(_collect_pids)

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
  # Multiple duplicates. Kill ALL — the caller must always spawn a fresh Monitor()
  # bound to the current session. Keeping an orphan (exit 0) leaves no Monitor task
  # in the new conversation's task registry, so webhook events never surface as
  # notifications (T-419 option a: kill and respawn is correct; option b is not).
  killed=0
  cur_pid=""
  for cur_pid in "${pids[@]}"; do
    kill "$cur_pid" 2>/dev/null && (( killed++ )) || true
  done
  echo "Killed ${killed} duplicate tail(s) on ${INBOX}; spawning fresh monitor." >&2
  exit 2
fi
