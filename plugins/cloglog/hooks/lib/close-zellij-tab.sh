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

if ! command -v jq &>/dev/null; then
  echo "close-zellij-tab.sh: jq required for list-tabs --json parsing" >&2
  exit 3
fi

# T-384: parse `list-tabs --json` (single contract) instead of column-grepping
# the human-readable form and `current-tab-info`. The JSON payload exposes
# `tab_id`, `name`, and an `active` boolean per tab — both lookups (target
# by name, focused tab id) come from one call.
TABS_JSON=$(zellij action list-tabs --json 2>/dev/null)

TAB_ID=$(jq -r --arg n "$WORKTREE_NAME" \
  '.[] | select(.name == $n) | .tab_id' <<<"$TABS_JSON" | head -n1)

if [[ -z "$TAB_ID" ]]; then
  # No tab with this name — nothing to close. Idempotent success.
  exit 0
fi

CURRENT_TAB_ID=$(jq -r '.[] | select(.active) | .tab_id' <<<"$TABS_JSON" | head -n1)

if [[ -n "$CURRENT_TAB_ID" ]] && [[ "$TAB_ID" == "$CURRENT_TAB_ID" ]]; then
  echo "close-zellij-tab.sh: refusing to close focused tab" \
       "(name=${WORKTREE_NAME}, tab_id=${TAB_ID}); this is the supervisor's" \
       "own tab — the caller must focus a different tab first or run from" \
       "outside this tab" >&2
  exit 2
fi

zellij action close-tab --tab-id "$TAB_ID"
