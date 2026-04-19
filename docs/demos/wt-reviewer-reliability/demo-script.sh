#!/usr/bin/env bash
# Demo: T-238 + T-239 — silent review failures now leave an audit trail on the PR.
# Called by `make demo`.
# This change is webhook-triggered (no new HTTP endpoint). The demo uses:
#   - source-level grep to prove each of the six skip sites is wired
#   - a deterministic pytest summary for the new tests
#   - a live dispatch of each skip reason against a respx-mocked GitHub API,
#     proving the bot would POST an issue-comment in production.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
BRANCH_DIR="${BRANCH//\//-}"
DEMO_FILE="docs/demos/$BRANCH_DIR/demo.md"

uvx showboat init "$DEMO_FILE" \
  "PR authors and human reviewers now see a PR comment every time the Codex bot declines to review — no more silent skips like PR #149 (timeout) or PR #159 (exit 1)."

# ---------------------------------------------------------------------------
# 1. Wiring proof — every short-circuit site reaches post_skip_comment.
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Wiring: each short-circuit site now calls the skip-comment helper."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -cE "_notify_skip\(|_post_agent_skip\(" src/gateway/review_engine.py'

uvx showboat note "$DEMO_FILE" \
  "Every SkipReason value is used at its corresponding site."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -oE "SkipReason\.[A-Z_]+" src/gateway/review_engine.py | sort -u'

# ---------------------------------------------------------------------------
# 2. Test evidence — one case per skip path, one for the retry, one for the
#    happy-path regression guard. Reduced to a deterministic pass count.
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "New tests — skip comments, retry/probe, happy-path regression guard."
uvx showboat exec "$DEMO_FILE" bash \
  'uv run pytest tests/gateway/test_review_engine.py -q 2>/dev/null | grep -oE "[0-9]+ passed"'

# ---------------------------------------------------------------------------
# 3. Live dispatch — drive the consumer against a mocked GitHub API and show
#    each skip path actually fires a POST to /issues/{pr}/comments.
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Live dispatch: each skip path fires exactly one comment POST."
uvx showboat exec "$DEMO_FILE" bash \
  'uv run python docs/demos/wt-reviewer-reliability/drive_skip_reasons.py'

# ---------------------------------------------------------------------------
# 4. Timeout path — the structured log entry fields that F-49 will mine.
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Timeout log entry schema (fields the F-49 supervisor will pattern-match)."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -oE "\"(event|pr_number|attempt|stderr_excerpt|codex_alive|github_reachable|elapsed_seconds)\":" src/gateway/review_engine.py | sort -u'

uvx showboat verify "$DEMO_FILE"
