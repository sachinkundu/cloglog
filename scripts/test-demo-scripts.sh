#!/bin/bash
set -euo pipefail

# Tests for the proof-of-work demo system scripts.
# Tests: worktree-ports.sh, check-demo.sh, Makefile integration.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0
REPORT=""

check() {
  local name="$1"
  local result="$2"
  if [[ "$result" == "PASS" ]]; then
    PASS=$((PASS + 1))
    REPORT+="- [x] **${name}**\n"
  else
    FAIL=$((FAIL + 1))
    REPORT+="- [ ] **${name}** — FAILED\n"
  fi
}

echo "# Demo Scripts — Test Report"
echo ""
echo "Generated: $(date -Iseconds)"
echo ""

# ══════════════════════════════════════════════════════════════
echo "## Test: worktree-ports.sh"
echo ""

# ── Test 1: Script produces deterministic ports ───────────────
echo '```'
WORKTREE_PATH="/tmp/test-wt-alpha" source scripts/worktree-ports.sh
PORT_A1="$BACKEND_PORT"
WORKTREE_PATH="/tmp/test-wt-alpha" source scripts/worktree-ports.sh
PORT_A2="$BACKEND_PORT"
echo "Run 1: BACKEND_PORT=$PORT_A1"
echo "Run 2: BACKEND_PORT=$PORT_A2"
echo '```'
echo ""
[[ "$PORT_A1" == "$PORT_A2" ]] && check "Ports are deterministic (same input → same output)" "PASS" || check "Ports are deterministic" "FAIL"

# ── Test 2: Different names produce different ports ───────────
echo '```'
WORKTREE_PATH="/tmp/test-wt-alpha" source scripts/worktree-ports.sh
PORT_ALPHA="$BACKEND_PORT"
WORKTREE_PATH="/tmp/test-wt-beta" source scripts/worktree-ports.sh
PORT_BETA="$BACKEND_PORT"
echo "wt-alpha: BACKEND_PORT=$PORT_ALPHA"
echo "wt-beta:  BACKEND_PORT=$PORT_BETA"
echo '```'
echo ""
[[ "$PORT_ALPHA" != "$PORT_BETA" ]] && check "Different worktree names produce different ports" "PASS" || check "Different names → different ports" "FAIL"

# ── Test 3: Ports are in valid range ──────────────────────────
echo '```'
WORKTREE_PATH="/tmp/test-wt-gamma" source scripts/worktree-ports.sh
echo "BACKEND_PORT=$BACKEND_PORT FRONTEND_PORT=$FRONTEND_PORT DB_PORT=$DB_PORT"
echo '```'
echo ""
[[ "$BACKEND_PORT" -ge 10000 && "$BACKEND_PORT" -le 60000 ]] && check "BACKEND_PORT in range 10000-60000" "PASS" || check "BACKEND_PORT in range" "FAIL"
[[ "$FRONTEND_PORT" -eq $((BACKEND_PORT + 1)) ]] && check "FRONTEND_PORT = BACKEND_PORT + 1" "PASS" || check "FRONTEND_PORT offset" "FAIL"
[[ "$DB_PORT" -eq $((BACKEND_PORT + 2)) ]] && check "DB_PORT = BACKEND_PORT + 2" "PASS" || check "DB_PORT offset" "FAIL"

# ── Test 4: DATABASE_URL is set correctly ─────────────────────
WORKTREE_PATH="/tmp/test-wt-gamma" source scripts/worktree-ports.sh
echo '```'
echo "WORKTREE_DB_NAME=$WORKTREE_DB_NAME"
echo "DATABASE_URL=$DATABASE_URL"
echo '```'
echo ""
[[ "$WORKTREE_DB_NAME" == "cloglog_test_wt_gamma" ]] && check "DB name derived correctly (hyphens → underscores)" "PASS" || check "DB name derivation" "FAIL"
echo "$DATABASE_URL" | grep -q "$WORKTREE_DB_NAME" && check "DATABASE_URL contains correct DB name" "PASS" || check "DATABASE_URL contains DB name" "FAIL"

# ══════════════════════════════════════════════════════════════
echo ""
echo "## Test: check-demo.sh"
echo ""

# ── Test 5: Skips on main branch ──────────────────────────────
# Test the branch detection logic directly — on main, the script exits 0 early.
# We simulate this by checking the script's logic: if branch == "main", exit 0.
echo '```'
# Verify the script contains the main branch skip logic
grep -q '"main"' scripts/check-demo.sh && echo "Script has main branch skip logic"
echo '```'
echo ""
grep -q '"main"' scripts/check-demo.sh && check "check-demo.sh has main branch skip logic" "PASS" || check "Skips on main" "FAIL"

# ── Test 6: Fails when demo is missing ────────────────────────
echo '```'
OUTPUT=$(DEMO_FEATURE="f99" scripts/check-demo.sh 2>&1) && EXIT=0 || EXIT=$?
echo "$OUTPUT"
echo "EXIT=$EXIT"
echo '```'
echo ""
[[ $EXIT -ne 0 ]] && check "check-demo.sh fails when demo dir is missing (exit non-zero)" "PASS" || check "Fails when missing" "FAIL"

# ── Test 7: Passes when demo.md exists ────────────────────────
echo '```'
mkdir -p docs/demos/f99-test-feature
echo "# Test Demo" > docs/demos/f99-test-feature/demo.md
OUTPUT=$(DEMO_FEATURE="f99" scripts/check-demo.sh 2>&1) && EXIT=0 || EXIT=$?
echo "$OUTPUT"
echo "EXIT=$EXIT"
rm -rf docs/demos/f99-test-feature
echo '```'
echo ""
[[ $EXIT -eq 0 ]] && check "check-demo.sh passes when demo.md exists" "PASS" || check "Passes when exists" "FAIL"

# ══════════════════════════════════════════════════════════════
echo ""
echo "## Test: Makefile targets"
echo ""

# ── Test 8: make demo-check target exists ─────────────────────
echo '```'
make -n demo-check 2>&1 && MAKE_EXIT=0 || MAKE_EXIT=$?
echo '```'
echo ""
[[ $MAKE_EXIT -eq 0 ]] && check "make demo-check target exists (dry-run succeeds)" "PASS" || check "demo-check target exists" "FAIL"

# ── Test 9: make demo target exists ───────────────────────────
echo '```'
make -n demo 2>&1 && MAKE_EXIT=0 || MAKE_EXIT=$?
echo '```'
echo ""
[[ $MAKE_EXIT -eq 0 ]] && check "make demo target exists (dry-run succeeds)" "PASS" || check "demo target exists" "FAIL"

# ══════════════════════════════════════════════════════════════
echo ""
echo "## Test: worktree-infra.sh"
echo ""

# ── Test 10: Usage message on bad input ───────────────────────
echo '```'
OUTPUT=$(scripts/worktree-infra.sh 2>&1) && EXIT=0 || EXIT=$?
echo "$OUTPUT"
echo "EXIT=$EXIT"
echo '```'
echo ""
[[ $EXIT -ne 0 ]] && echo "$OUTPUT" | grep -q "Usage" && check "worktree-infra.sh shows usage on no args" "PASS" || check "Shows usage" "FAIL"

# ══════════════════════════════════════════════════════════════
echo ""
echo "## Results"
echo ""
echo -e "$REPORT"
echo ""
TOTAL=$((PASS + FAIL))
echo "**${PASS}/${TOTAL} passed**, ${FAIL} failed"

[[ $FAIL -eq 0 ]] && exit 0 || exit 1
