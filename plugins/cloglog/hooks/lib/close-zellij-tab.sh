#!/usr/bin/env bash
# Safely close the zellij tab whose name matches a worktree.
#
# `zellij action close-tab` takes no positional argument and closes the
# *currently focused* tab — never the tab whose name you intended. Twice
# the supervisor's own tab has been killed by callers that paired
# `query-tab-names` with a bare `close-tab` (T-339). This helper resolves
# the target by name, refuses to close the supervisor's own tab, and only
# then issues a tab-id-scoped close.
#
# Usage: close-zellij-tab.sh <worktree-name>
#
# Exit codes:
#   0 — closed the named tab, OR the named tab does not exist
#       (idempotent — caller should not treat absence as failure), OR
#       not running under zellij (no-op).
#   2 — refused: target tab is the focused tab. Caller MUST surface this
#       as a hard error, not swallow it. Closing the focused tab kills
#       the supervisor session.
#   3 — usage error or zellij unavailable when ZELLIJ is set.

set -euo pipefail

if [[ $# -ne 1 ]] || [[ -z "${1:-}" ]]; then
  echo "close-zellij-tab.sh: usage: $0 <worktree-name>" >&2
  exit 3
fi

WORKTREE_NAME="$1"

# Not in zellij — nothing to do.
if [[ -z "${ZELLIJ:-}" ]]; then
  exit 0
fi

if ! command -v zellij &>/dev/null; then
  echo "close-zellij-tab.sh: ZELLIJ is set but zellij binary missing" >&2
  exit 3
fi

# Resolve the target tab id from the name. list-tabs columns:
#   TAB_ID  POSITION  NAME
TAB_ID=$(zellij action list-tabs 2>/dev/null \
  | awk -v name="$WORKTREE_NAME" '$3 == name {print $1; exit}')

if [[ -z "$TAB_ID" ]]; then
  # No tab with this name — nothing to close. Idempotent success.
  exit 0
fi

# Read the focused tab id. current-tab-info prints `id: N` on its own line.
CURRENT_TAB_ID=$(zellij action current-tab-info 2>/dev/null \
  | awk -F': ' '$1 == "id" {print $2; exit}')

if [[ -n "$CURRENT_TAB_ID" ]] && [[ "$TAB_ID" == "$CURRENT_TAB_ID" ]]; then
  echo "close-zellij-tab.sh: refusing to close focused tab" \
       "(name=${WORKTREE_NAME}, tab_id=${TAB_ID}); this is the supervisor's" \
       "own tab — the caller must focus a different tab first or run from" \
       "outside this tab" >&2
  exit 2
fi

zellij action close-tab --tab-id "$TAB_ID"
