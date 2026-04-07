#!/bin/bash
# System reconciliation: detect and fix drift between board, agents, worktrees, PRs, branches.
# Usage: scripts/reconcile.sh [--fix]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API="http://localhost:8000/api/v1"
REPO="sachinkundu/cloglog"
FIX_MODE=false
ISSUES=0
FIXED=0

[[ "${1:-}" == "--fix" ]] && FIX_MODE=true

# Colors
RED='\033[0;31m'
YEL='\033[0;33m'
GRN='\033[0;32m'
RST='\033[0m'

warn()  { echo -e "  ${YEL}⚠${RST} $*"; ISSUES=$((ISSUES + 1)); }
ok()    { echo -e "  ${GRN}✓${RST} $*"; }
fixed() { echo -e "  ${GRN}✓ fixed:${RST} $*"; FIXED=$((FIXED + 1)); }
err()   { echo -e "  ${RED}✗${RST} $*"; ISSUES=$((ISSUES + 1)); }

# Helper: extract PR number from URL
pr_num() { echo "$1" | grep -oP '#?\K\d+$' || echo ""; }

# Helper: get PR state
pr_state() {
  local num="$1"
  gh pr view "$num" --repo "$REPO" --json state -q '.state' 2>/dev/null || echo "UNKNOWN"
}

# Helper: get PR comment count after a date
pr_comments_after() {
  local num="$1" after="$2"
  gh api "repos/$REPO/issues/$num/comments" --jq "[.[] | select(.created_at > \"$after\")] | length" 2>/dev/null || echo "0"
}

# Helper: get last push date for a PR branch
pr_last_push() {
  local num="$1"
  gh pr view "$num" --repo "$REPO" --json commits -q '.commits[-1].committedDate' 2>/dev/null || echo ""
}

echo "=== System Reconciliation Report ==="
echo ""

# ─── 1. Task ↔ PR State ───────────────────────────────────
echo "Tasks:"

# Get all tasks in review or in_progress with pr_url
REVIEW_TASKS=$(curl -sf "$API/projects" | python3 -c "
import json, sys
projects = json.load(sys.stdin)
for p in projects:
    pid = p['id']
    board = json.loads(__import__('urllib.request', fromlist=['urlopen']).urlopen(f'$API/projects/{pid}/board').read())
    for col in board['columns']:
        if col['status'] in ('review', 'in_progress'):
            for t in col['tasks']:
                pr = t.get('pr_url') or ''
                if pr:
                    print(f\"{t['number']}|{t['status']}|{pr}|{t['id']}|{t['title'][:50]}\")
" 2>/dev/null || echo "")

if [[ -z "$REVIEW_TASKS" ]]; then
  ok "No tasks with PRs in review/in_progress"
else
  while IFS='|' read -r tnum tstatus tpr tid ttitle; do
    pnum=$(pr_num "$tpr")
    [[ -z "$pnum" ]] && continue
    state=$(pr_state "$pnum")

    case "$tstatus:$state" in
      review:MERGED)
        warn "T-$tnum ($ttitle) — PR #$pnum is MERGED → should be done"
        if $FIX_MODE; then
          curl -sf -X PATCH "$API/tasks/$tid" -H "Content-Type: application/json" \
            -d "{\"status\": \"done\"}" >/dev/null 2>&1 && fixed "T-$tnum → done" || err "Failed to fix T-$tnum"
        fi
        ;;
      review:CLOSED)
        warn "T-$tnum ($ttitle) — PR #$pnum is CLOSED → needs attention"
        ;;
      review:OPEN)
        # Check for unaddressed comments
        last_push=$(pr_last_push "$pnum")
        if [[ -n "$last_push" ]]; then
          new_comments=$(pr_comments_after "$pnum" "$last_push")
          if [[ "$new_comments" -gt 0 ]]; then
            warn "T-$tnum ($ttitle) — PR #$pnum has $new_comments unaddressed comment(s)"
          else
            ok "T-$tnum — PR #$pnum is OPEN, no unaddressed comments"
          fi
        else
          ok "T-$tnum — PR #$pnum is OPEN"
        fi
        ;;
      in_progress:MERGED)
        warn "T-$tnum ($ttitle) — PR #$pnum is MERGED but task still in_progress"
        ;;
      *)
        ok "T-$tnum — PR #$pnum is $state, task is $tstatus"
        ;;
    esac
  done <<< "$REVIEW_TASKS"
fi

echo ""

# ─── 2. Agent ↔ Task ──────────────────────────────────────
echo "Agents:"

WORKTREES_JSON=$(curl -sf "$API/projects" | python3 -c "
import json, sys
projects = json.load(sys.stdin)
for p in projects:
    pid = p['id']
    wts = json.loads(__import__('urllib.request', fromlist=['urlopen']).urlopen(f'$API/projects/{pid}/worktrees').read())
    for w in wts:
        print(f\"{w['id']}|{w['name']}|{w['status']}|{w.get('current_task_id', 'none')}|{w.get('last_heartbeat', 'none')}\")
" 2>/dev/null || echo "")

if [[ -z "$WORKTREES_JSON" ]]; then
  ok "No registered agents"
else
  while IFS='|' read -r wid wname wstatus wcurrent whb; do
    # Get tasks assigned to this worktree
    task_count=$(curl -sf "$API/agents/$wid/tasks" | python3 -c "
import json, sys
tasks = json.load(sys.stdin)
active = [t for t in tasks if t['status'] not in ('done',)]
print(len(active))
" 2>/dev/null || echo "0")

    if [[ "$task_count" == "0" ]]; then
      warn "Agent $wname — no active tasks assigned → should unregister"
      if $FIX_MODE; then
        curl -sf -X POST "$API/agents/$wid/unregister" >/dev/null 2>&1 && fixed "Unregistered agent $wname" || err "Failed to unregister $wname"
      fi
    else
      # Check if any task in review has unaddressed PR comments
      review_info=$(curl -sf "$API/agents/$wid/tasks" | python3 -c "
import json, sys
tasks = json.load(sys.stdin)
for t in tasks:
    if t['status'] == 'review':
        print(f\"{t.get('number', '?')}|review\")
        break
" 2>/dev/null || echo "")
      if [[ -n "$review_info" ]]; then
        ok "Agent $wname — $task_count active task(s), has task in review"
      else
        ok "Agent $wname — $task_count active task(s)"
      fi
    fi
  done <<< "$WORKTREES_JSON"
fi

echo ""

# ─── 3. Worktree ↔ Agent ──────────────────────────────────
echo "Worktrees:"

cd "$REPO_ROOT"
WORKTREE_DIRS=$(git worktree list --porcelain | grep "^worktree " | sed 's/^worktree //' | grep '\.claude/worktrees/wt-' || echo "")

if [[ -z "$WORKTREE_DIRS" ]]; then
  ok "No active worktrees"
else
  while IFS= read -r wdir; do
    wname=$(basename "$wdir")
    branch=$(cd "$wdir" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

    # Check if branch is fully merged
    if git branch --merged main 2>/dev/null | grep -q "$branch"; then
      warn "Worktree $wname — branch '$branch' fully merged into main → can be removed"
      if $FIX_MODE; then
        "$REPO_ROOT/scripts/manage-worktrees.sh" remove "$wname" >/dev/null 2>&1 && fixed "Removed worktree $wname" || err "Failed to remove $wname"
      fi
    else
      ok "Worktree $wname — has unmerged work on '$branch'"
    fi
  done <<< "$WORKTREE_DIRS"
fi

echo ""

# ─── 4. Branch Cleanup ────────────────────────────────────
echo "Branches:"

# Local merged branches
LOCAL_MERGED=$(git branch --merged main 2>/dev/null | grep -v '^\*\|main$\|wt-' | tr -d ' ' || echo "")
LOCAL_COUNT=0
if [[ -n "$LOCAL_MERGED" ]]; then
  LOCAL_COUNT=$(echo "$LOCAL_MERGED" | wc -l | tr -d ' ')
fi

if [[ "$LOCAL_COUNT" -gt 0 ]]; then
  warn "$LOCAL_COUNT local merged branch(es) can be deleted"
  if $FIX_MODE; then
    while IFS= read -r b; do
      [[ -z "$b" ]] && continue
      git branch -d "$b" >/dev/null 2>&1 && fixed "Deleted local branch $b"
    done <<< "$LOCAL_MERGED"
  fi
else
  ok "No stale local branches"
fi

# Remote stale branches
git fetch --prune origin >/dev/null 2>&1 || true
REMOTE_BRANCHES=$(git branch -r 2>/dev/null | grep -v 'origin/main\|origin/HEAD' | sed 's|origin/||' | tr -d ' ' || echo "")
REMOTE_STALE=0
REMOTE_STALE_LIST=""

while IFS= read -r rb; do
  [[ -z "$rb" ]] && continue
  # Check if this remote branch has an open PR
  has_open_pr=$(gh pr list --repo "$REPO" --head "$rb" --state open --json number -q 'length' 2>/dev/null || echo "0")
  if [[ "$has_open_pr" == "0" ]]; then
    # No open PR — check if merged into main
    if git branch -r --merged origin/main 2>/dev/null | grep -q "origin/$rb"; then
      REMOTE_STALE=$((REMOTE_STALE + 1))
      REMOTE_STALE_LIST="$REMOTE_STALE_LIST $rb"
    fi
  fi
done <<< "$REMOTE_BRANCHES"

if [[ "$REMOTE_STALE" -gt 0 ]]; then
  warn "$REMOTE_STALE remote stale branch(es) can be deleted"
  if $FIX_MODE; then
    for rb in $REMOTE_STALE_LIST; do
      git push origin --delete "$rb" >/dev/null 2>&1 && fixed "Deleted remote branch $rb" || true
    done
  fi
else
  ok "No stale remote branches"
fi

echo ""

# ─── 5. Open PR Audit ─────────────────────────────────────
echo "PRs:"

OPEN_PRS=$(gh pr list --repo "$REPO" --state open --json number,title,headRefName -q '.[] | "\(.number)|\(.title)|\(.headRefName)"' 2>/dev/null || echo "")

if [[ -z "$OPEN_PRS" ]]; then
  ok "No open PRs"
else
  while IFS='|' read -r pnum ptitle pbranch; do
    [[ -z "$pnum" ]] && continue
    # Check if branch still exists
    if ! git rev-parse --verify "origin/$pbranch" >/dev/null 2>&1; then
      warn "PR #$pnum ($ptitle) — branch '$pbranch' no longer exists"
      if $FIX_MODE; then
        BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests ~/.agent-vm/credentials/gh-app-token.py 2>/dev/null || echo "")
        if [[ -n "$BOT_TOKEN" ]]; then
          GH_TOKEN="$BOT_TOKEN" gh pr close "$pnum" --repo "$REPO" --comment "Closed by reconciliation: branch no longer exists" >/dev/null 2>&1 && fixed "Closed PR #$pnum"
        fi
      fi
    else
      ok "PR #$pnum — branch exists"
    fi
  done <<< "$OPEN_PRS"
fi

echo ""

# ─── Summary ──────────────────────────────────────────────
echo "=== Summary: $ISSUES issue(s) found, $FIXED auto-fixed ==="

if [[ "$ISSUES" -gt 0 ]] && ! $FIX_MODE; then
  echo ""
  echo "Run with --fix to auto-correct safe issues:"
  echo "  scripts/reconcile.sh --fix"
fi
