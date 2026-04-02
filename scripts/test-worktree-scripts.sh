#!/bin/bash
set -euo pipefail

# End-to-end test for worktree automation scripts.
# Outputs a markdown test report to stdout.

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

capture() {
  # Run a command, capture output, return pass/fail
  local output
  output=$("$@" 2>&1) && echo "PASS" || echo "FAIL"
  echo "$output" >&2
}

echo "# Worktree Scripts — Test Report"
echo ""
echo "Generated: $(date -Iseconds)"
echo ""
echo "## Test: create-worktree.sh"
echo ""

# ── Test 1: Create a known worktree (wt-board) ──────────────
echo '```'
CREATE_OUTPUT=$(./scripts/create-worktree.sh wt-board docs/superpowers/plans/2026-03-31-phase-0-scaffold.md "Test: Board context scaffold" 2>&1)
CREATE_EXIT=$?
echo "$CREATE_OUTPUT"
echo '```'
echo ""

[[ $CREATE_EXIT -eq 0 ]] && check "create-worktree.sh exits 0" "PASS" || check "create-worktree.sh exits 0" "FAIL"

# ── Test 2: Worktree directory exists ────────────────────────
WORKTREE_DIR="$REPO_ROOT/.claude/worktrees/wt-board"
[[ -d "$WORKTREE_DIR" ]] && check "Worktree directory exists at .claude/worktrees/wt-board" "PASS" || check "Worktree directory exists" "FAIL"

# ── Test 3: Branch was created ───────────────────────────────
BRANCH_EXISTS=$(git branch --list wt-board | wc -l | tr -d ' ')
[[ "$BRANCH_EXISTS" -eq 1 ]] && check "Git branch 'wt-board' created" "PASS" || check "Git branch 'wt-board' created" "FAIL"

# ── Test 4: CLAUDE.md was generated ──────────────────────────
[[ -f "$WORKTREE_DIR/CLAUDE.md" ]] && check "CLAUDE.md generated in worktree" "PASS" || check "CLAUDE.md generated" "FAIL"

# ── Test 5: CLAUDE.md contains correct identity ─────────────
echo "### Generated CLAUDE.md"
echo ""
echo '```markdown'
cat "$WORKTREE_DIR/CLAUDE.md"
echo '```'
echo ""

grep -q "wt-board" "$WORKTREE_DIR/CLAUDE.md" && check "CLAUDE.md contains worktree name 'wt-board'" "PASS" || check "CLAUDE.md contains worktree name" "FAIL"
grep -q "Board bounded context" "$WORKTREE_DIR/CLAUDE.md" && check "CLAUDE.md contains context name 'Board bounded context'" "PASS" || check "CLAUDE.md contains context name" "FAIL"
grep -q "src/board/" "$WORKTREE_DIR/CLAUDE.md" && check "CLAUDE.md contains allowed directories 'src/board/'" "PASS" || check "CLAUDE.md contains allowed dirs" "FAIL"
grep -q "make test-board" "$WORKTREE_DIR/CLAUDE.md" && check "CLAUDE.md contains test command 'make test-board'" "PASS" || check "CLAUDE.md contains test command" "FAIL"
grep -q "2026-03-31-phase-0-scaffold.md" "$WORKTREE_DIR/CLAUDE.md" && check "CLAUDE.md references plan file" "PASS" || check "CLAUDE.md references plan" "FAIL"

# ── Test 6: Python deps installed ────────────────────────────
[[ -d "$WORKTREE_DIR/.venv" ]] && check "Python .venv created in worktree" "PASS" || check "Python .venv created" "FAIL"

# ── Test 7: Frontend deps installed ──────────────────────────
[[ -d "$WORKTREE_DIR/frontend/node_modules" ]] && check "Frontend node_modules installed" "PASS" || check "Frontend node_modules installed" "FAIL"

# ── Test 8: MCP server deps installed ────────────────────────
[[ -d "$WORKTREE_DIR/mcp-server/node_modules" ]] && check "MCP server node_modules installed" "PASS" || check "MCP server node_modules installed" "FAIL"

# ── Test 9: Tests run in the worktree ────────────────────────
echo "## Test: running tests inside worktree"
echo ""
echo '```'
TEST_OUTPUT=$(cd "$WORKTREE_DIR" && uv run pytest tests/board/ -v --tb=short 2>&1)
TEST_EXIT=$?
echo "$TEST_OUTPUT"
echo '```'
echo ""
[[ $TEST_EXIT -eq 0 ]] && check "pytest tests/board/ passes inside worktree" "PASS" || check "pytest passes inside worktree" "FAIL"

# ── Test 10: Duplicate creation fails ────────────────────────
echo "## Test: duplicate creation blocked"
echo ""
echo '```'
DUP_OUTPUT=$(./scripts/create-worktree.sh wt-board 2>&1) && DUP_EXIT=0 || DUP_EXIT=$?
echo "$DUP_OUTPUT"
echo '```'
echo ""
[[ $DUP_EXIT -ne 0 ]] && check "Duplicate worktree creation blocked (exits non-zero)" "PASS" || check "Duplicate creation blocked" "FAIL"

# ── Test 11: list-worktrees.sh ───────────────────────────────
echo "## Test: list-worktrees.sh"
echo ""
echo '```'
LIST_OUTPUT=$(./scripts/list-worktrees.sh 2>&1)
echo "$LIST_OUTPUT"
echo '```'
echo ""
echo "$LIST_OUTPUT" | grep -q "wt-board" && check "list-worktrees.sh shows wt-board" "PASS" || check "list shows wt-board" "FAIL"

# ── Test 12: remove-worktree.sh ──────────────────────────────
echo "## Test: remove-worktree.sh"
echo ""
echo '```'
REMOVE_OUTPUT=$(./scripts/remove-worktree.sh --force wt-board 2>&1)
REMOVE_EXIT=$?
echo "$REMOVE_OUTPUT"
echo '```'
echo ""
[[ $REMOVE_EXIT -eq 0 ]] && check "remove-worktree.sh exits 0" "PASS" || check "remove exits 0" "FAIL"
[[ ! -d "$WORKTREE_DIR" ]] && check "Worktree directory removed" "PASS" || check "Worktree directory removed" "FAIL"
BRANCH_AFTER=$(git branch --list wt-board | wc -l | tr -d ' ')
[[ "$BRANCH_AFTER" -eq 0 ]] && check "Branch 'wt-board' deleted" "PASS" || check "Branch deleted" "FAIL"

# ── Test 13: Unknown worktree name warns but works ───────────
echo "## Test: unknown worktree name"
echo ""
echo '```'
UNK_OUTPUT=$(./scripts/create-worktree.sh wt-custom-thing 2>&1)
echo "$UNK_OUTPUT"
echo '```'
echo ""
echo "$UNK_OUTPUT" | grep -q "Warning: unknown" && check "Unknown worktree name shows warning" "PASS" || check "Unknown name warning" "FAIL"

# Clean up the unknown worktree
./scripts/remove-worktree.sh --force wt-custom-thing > /dev/null 2>&1 || true

# ── Summary ──────────────────────────────────────────────────
echo ""
echo "## Results"
echo ""
echo -e "$REPORT"
echo ""
TOTAL=$((PASS + FAIL))
echo "**${PASS}/${TOTAL} passed**, ${FAIL} failed"
