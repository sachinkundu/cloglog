#!/usr/bin/env bash
# Demo for T-288: wire `make invariants` as a fail-fast prefix to
# `make quality`. Verify-safe: grep booleans + line-order checks
# against the committed Makefile. No pytest, no DB, no network.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"

rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "If a silent-failure invariant regresses, you see it in under a second instead of after a 100-second test run."

# ==================================================================
uvx showboat note "$DEMO_FILE" "### The invariants pin-test set is now the first thing \`make quality\` runs

Before: \`make quality\` started with lint → typecheck → tests. A pin-test
regression surfaced only after the full \`tests/\` run (~100s). After:
\`make invariants\` runs first (~1s, 28 tests). On regression, the gate
fails fast and names the invariant file explicitly."

# ----- Quality target declares the Invariants section first -----
uvx showboat exec "$DEMO_FILE" bash \
  'awk "/^quality:/{flag=1} flag && /── Invariants ──/ {print \"invariants_section_present=yes\"; exit} flag && /── Backend ──/ {print \"invariants_section_present=NO_comes_after_backend\"; exit}" Makefile'

# ----- Invariants block precedes Backend block inside quality -----
uvx showboat exec "$DEMO_FILE" bash \
  'quality_start=$(grep -n "^quality:" Makefile | head -1 | cut -d: -f1)
   inv_line=$(awk -v start="$quality_start" "NR>=start && /── Invariants ──/ {print NR; exit}" Makefile)
   backend_line=$(awk -v start="$quality_start" "NR>=start && /── Backend ──/ {print NR; exit}" Makefile)
   if [ -n "$inv_line" ] && [ -n "$backend_line" ] && [ "$inv_line" -lt "$backend_line" ]; then
     echo "ordering=invariants_before_backend"
   else
     echo "ordering=WRONG_inv=${inv_line}_backend=${backend_line}"
   fi'

# ----- Failure message points at the manifest, not just "FAILED" -----
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "a silent-failure invariant regressed. See docs/invariants.md" Makefile \
     && echo "failure_points_at_manifest=yes" || echo "failure_points_at_manifest=MISSING"'

# ----- Existing invariants target still exists and is the one being called -----
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "^invariants:" Makefile && echo "invariants_target_intact=yes" || echo "invariants_target_intact=MISSING"
   grep -q "\$(MAKE) --no-print-directory invariants" Makefile && echo "quality_recurses_into_invariants=yes" || echo "quality_recurses_into_invariants=MISSING"'

# ==================================================================
uvx showboat note "$DEMO_FILE" "### No semantic change — same tests run, just ordered to fail fast

The 28 pin tests already ran inside \`make test\` (which is inside
\`make quality\`). This PR only reorders execution; the set of
regressions caught is exactly the same. The win is feedback latency
when a pin-test is the actual cause of failure."

# ----- Pin tests continue to run under `make test` too (via tests/) -----
uvx showboat exec "$DEMO_FILE" bash \
  'count=$(grep -cE "^\s+tests/" Makefile || true)
   [ "$count" -gt 0 ] && echo "invariants_target_lists_tests=yes" || echo "invariants_target_lists_tests=NO"
   grep -q "uv run pytest tests/ -v --tb=short" Makefile && echo "test_target_still_runs_full_tree=yes" || echo "test_target_still_runs_full_tree=MISSING"'

uvx showboat verify "$DEMO_FILE"
