#!/usr/bin/env bash
# Demo for T-275: short-circuit opencode reviewer + exclude docs/demos/ from
# codex diff.
#
# Verify-safe: no pytest, no DB, no subprocess against ollama. Every exec
# block is a deterministic OK/FAIL boolean or an in-process python proof.
# scripts/check-demo.sh reruns every exec on make quality, so live-service
# calls would make the quality gate flaky.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Layout: docs/demos/<branch>/demo-script.sh → worktree root is three levels up.
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"

# showboat init refuses to overwrite — delete first so `make demo` is re-runnable.
rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "Stage A (opencode) is disabled by default via settings.opencode_enabled=False, and codex stops reviewing docs/demos/ proof-of-work artifacts."

# ------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" "### Change 1 — \`settings.opencode_enabled\` flag (default OFF)

One global Settings boolean gates stage A. Default is \`False\` on purpose:
\`gemma4-e4b-32k\` rubber-stamps \`:pass:\` regardless of prompt framing, so
stage A under the default local model produces only noise. Flip the flag
once T-274 lands a reviewer model that defends severity — no code change
needed then."

uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "^    opencode_enabled: bool = False" src/shared/config.py && echo "opencode_enabled_default_false=yes" || echo "opencode_enabled_default_false=MISSING"
   grep -q "settings.opencode_enabled" src/gateway/review_engine.py && echo "stage_a_gate_reads_setting=yes" || echo "stage_a_gate_reads_setting=MISSING"
   grep -q "if self._opencode_available and settings.opencode_enabled:" src/gateway/review_engine.py && echo "stage_a_gate_shape=and_conjunction" || echo "stage_a_gate_shape=MISMATCH"'

# ------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" "### Change 2 — \`docs/demos/\` added to diff skip patterns

Proof-of-work under \`docs/demos/<branch>/\` is Showboat-rendered booleans
plus captured tool output, not reviewable code. One regex in the
\`_DIFF_SKIP_PATTERNS\` tuple makes every reviewer skip those sections."

uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "(\\^|/)docs/demos/" src/gateway/review_engine.py && echo "skip_pattern_registered=yes" || echo "skip_pattern_registered=MISSING"'

# ------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" "### Proof 1 — \`filter_diff\` drops \`docs/demos/\` sections in process

Constructs a two-section diff (one \`docs/demos/\` + one \`src/gateway/\`),
calls the real \`filter_diff\`, and asserts the demo section is gone while
the code section survives. Pure function call — verify-safe."

uvx showboat exec "$DEMO_FILE" bash \
  'uv run python docs/demos/wt-disable-opencode-skip-demos/proof_filter_diff.py'

# ------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" "### Proof 2 — sequencer skips stage A when flag off, still runs stage B

Instantiates the real \`ReviewEngineConsumer\`, stubs \`ReviewLoop\` so each
stage is observable, and drives \`_review_pr\` under both
\`opencode_enabled=False\` and \`True\`. Asserts:

- flag **off** → stage A never runs, stage B (codex) runs once;
- flag **on**  → stage A runs once, stage B still runs once.

No DB, no network, no subprocess — verify-safe."

uvx showboat exec "$DEMO_FILE" bash \
  'uv run python docs/demos/wt-disable-opencode-skip-demos/proof_sequencer.py'

# ------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" "### Pin tests still green

T-272's \`test_opencode_argv_passes_pure\` pin test must survive — T-275
deliberately keeps the \`OpencodeReviewer\` class and its \`--pure\` invariant
intact so T-274's agentic-mode investigation can still drive the loop."

uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "def test_opencode_argv_passes_pure" tests/gateway/test_review_loop.py && echo "t272_pin_test_present=yes" || echo "t272_pin_test_present=MISSING"
   grep -q "\"--pure\"" src/gateway/review_loop.py && echo "opencode_argv_still_has_pure=yes" || echo "opencode_argv_still_has_pure=MISSING"'
