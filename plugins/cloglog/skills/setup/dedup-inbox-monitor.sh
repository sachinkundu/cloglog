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
# Cross-project safety: the pattern anchors on the full absolute inbox path so
# monitors belonging to other projects on the same host are not touched.

set -euo pipefail

INBOX="${1:?usage: dedup-inbox-monitor.sh <inbox_absolute_path>}"

# ── collect PIDs watching exactly this inbox ──────────────────────────────
# Field 2 ($2) is the command name.  We require it to be "tail" or end with
# "/tail" so that wrapper bash processes whose command line happens to contain
# the word "tail" (e.g. the inbox path itself contains "tails") are not
# mistakenly matched.  `$NF == inbox` anchors the last argument exactly to
# this inbox path — no suffix, no other project's path.
mapfile -t pids < <(
  ps -ww -eo pid=,args= 2>/dev/null \
    | awk -v inbox="$INBOX" '$2 ~ /\/tail$|^tail$/ && $NF == inbox {print $1}' \
  || true
)

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
