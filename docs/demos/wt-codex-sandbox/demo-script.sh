#!/usr/bin/env bash
# Demo: The PR review webhook now invokes codex with
# --dangerously-bypass-approvals-and-sandbox, so bwrap is never launched
# and the reviewer can actually read project files.
#
# Called by make demo. The backend is started by run-demo.sh but this
# demo does not need it — the evidence is: (a) the live failure from
# PR #152's own review comment, (b) codex CLI confirms the bypass flag
# exists, (c) the argv diff in review_engine.py, (d) a pinned regression
# test preventing any revert, (e) codex reachable with the new flag.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

DEMO_FILE="docs/demos/$(git rev-parse --abbrev-ref HEAD)/demo.md"

uvx showboat init "$DEMO_FILE" \
  "PR reviews now run codex without bwrap, fixing the RTM_NEWADDR failure that made every review on PR #152 fall back to a 'sandbox error' message instead of real analysis."

# ---------------------------------------------------------------------------
# 1. The live failure we are fixing
# ---------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
  "Evidence 1 — This is the actual review the cloglog-codex-reviewer bot posted on PR #152 earlier today. The failure mode is public and reproducible: whenever codex's shell-tool fires, bwrap's unshare-net dies with RTM_NEWADDR because this host lacks CAP_NET_ADMIN. Without the fix, every review produces this fallback message instead of findings."

uvx showboat exec "$DEMO_FILE" bash \
  'gh api repos/sachinkundu/cloglog/pulls/152/reviews --jq ".[0].body" | grep -o "bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted"'

# ---------------------------------------------------------------------------
# 2. codex CLI confirms the bypass flag exists and is the right tool
# ---------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
  "Evidence 2 — codex exec --help confirms --dangerously-bypass-approvals-and-sandbox is a real, first-class flag. Its description explicitly says it is intended for environments that are externally sandboxed — exactly this agent-vm setup. This is the only codex flag that skips bwrap entirely; every --sandbox mode (including danger-full-access) still invokes bwrap to enforce network isolation."

uvx showboat exec "$DEMO_FILE" bash \
  'codex exec --help 2>&1 | grep -A1 "dangerously-bypass-approvals-and-sandbox" | head -3'

# ---------------------------------------------------------------------------
# 3. The argv change that fixes it
# ---------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
  "Evidence 3 — src/gateway/review_engine.py now passes --dangerously-bypass-approvals-and-sandbox in place of --full-auto + --sandbox danger-full-access. The new comment block explains why, so the next cleanup pass cannot silently put bwrap back."

uvx showboat exec "$DEMO_FILE" bash \
  'git diff origin/main -- src/gateway/review_engine.py | grep -E "^[-+]" | grep -v "^[-+][-+][-+]"'

# ---------------------------------------------------------------------------
# 4. Codex reachable with the new flag (subprocess works, no bwrap error)
# ---------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
  "Evidence 4 — With the new flag, codex is reachable from a subprocess. A trivial prompt round-trips through the model without any 'bwrap: loopback' line in stderr. We grep for the OK reply and explicitly assert the bwrap signature is absent."

uvx showboat exec "$DEMO_FILE" bash \
  'out=$(timeout 30 codex exec --dangerously-bypass-approvals-and-sandbox --ephemeral --color never "reply with the single word OK and nothing else" 2>&1); echo "$out" | grep -q "^OK$" && echo "model replied: OK"; echo "$out" | grep -q "bwrap: loopback" && echo "BUG: bwrap still invoked" || echo "bwrap not invoked: confirmed"'

# ---------------------------------------------------------------------------
# 5. Regression-guard test pins the argv shape
# ---------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
  "Evidence 5 — A new pytest asserts the bypass flag is present and --sandbox / --full-auto / danger-full-access are all absent from the codex argv. This guards against a 'tidy up' revert — if anyone puts --sandbox back, this test fails."

uvx showboat exec "$DEMO_FILE" bash \
  'uv run pytest tests/gateway/test_review_engine.py::TestHandleOrchestration::test_codex_argv_uses_bypass_flag_not_sandbox -q 2>&1 | grep -oE "[0-9]+ passed"'

# ---------------------------------------------------------------------------
# 6. Full review_engine test module still green
# ---------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
  "Evidence 6 — All 64 tests in the review_engine module pass with the new argv (63 existing + 1 new regression guard). Nothing else had to change."

uvx showboat exec "$DEMO_FILE" bash \
  'uv run pytest tests/gateway/test_review_engine.py -q 2>&1 | grep -oE "[0-9]+ passed"'

uvx showboat verify "$DEMO_FILE"
