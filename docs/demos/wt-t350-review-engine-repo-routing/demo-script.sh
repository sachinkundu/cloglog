#!/usr/bin/env bash
# Demo: review engine refuses to review a PR for a repo not in
# review_repo_roots, while still routing close-wave PRs for configured
# repos. Re-runnable: rm -f docs/demos/<branch>/demo.md before re-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"

cd "$REPO_ROOT"

rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "T-350: review engine no longer reviews cross-repo PRs against the wrong repository's source"

uvx showboat note "$DEMO_FILE" \
  "Background: antisocial PR #2 (branch wt-close-2026-04-29-wave-1) was reviewed against cloglog's source. The resolver was repo-blind — Path 1 (branch lookup) missed because the close-wave branch had no worktree row, and Path 2 fell back to settings.review_source_root (cloglog-prod) without consulting event.repo_full_name."

uvx showboat note "$DEMO_FILE" \
  "The fix: settings.review_repo_roots — a per-repo registry consulted before the legacy fallback. When populated, the resolver REFUSES (returns None) on unconfigured repos and the engine posts a one-shot unconfigured_repo skip comment instead of running codex against the wrong repo."

uvx showboat note "$DEMO_FILE" \
  "Driving the resolver directly with two synthetic webhook events. The proof script imports resolve_pr_review_root, sets a registry containing only sachinkundu/cloglog, and points settings.review_source_root at cloglog-prod (so a regression that ignored the registry would visibly route the antisocial PR there — failing the assert)."

uvx showboat exec "$DEMO_FILE" bash \
  'uv run --quiet python docs/demos/wt-t350-review-engine-repo-routing/proof_resolver.py'

uvx showboat note "$DEMO_FILE" \
  "Pin tests: five new acceptance pin tests live in tests/gateway/test_review_engine.py::TestResolvePrReviewRootRepoRouting. Recap (counted from the test source so the count cannot drift)."

uvx showboat exec "$DEMO_FILE" bash \
  'grep -c "    async def test_" tests/gateway/test_review_engine.py | xargs -I{} echo "TestResolvePrReviewRoot* tests in test_review_engine.py: {}"'

uvx showboat exec "$DEMO_FILE" bash \
  'grep -E "^    async def test_" tests/gateway/test_review_engine.py | grep -E "(skips_unrelated_repo|close_wave_pr_on_cloglog_still_routes|existing_worktree_branch_lookup_unchanged|review_repo_roots_registry_lookup)" | wc -l | xargs -I{} echo "T-350 acceptance pins present: {}"'

uvx showboat note "$DEMO_FILE" \
  "Engine integration: when the resolver returns None, _review_pr posts an UNCONFIGURED_REPO SkipReason via _notify_skip and returns — codex is never spawned for the unconfigured repo."

uvx showboat exec "$DEMO_FILE" bash \
  'grep -c "SkipReason.UNCONFIGURED_REPO" src/gateway/review_engine.py | xargs -I{} echo "UNCONFIGURED_REPO callsites in review_engine.py: {}"'

uvx showboat exec "$DEMO_FILE" bash \
  'grep -c "UNCONFIGURED_REPO" src/gateway/review_skip_comments.py | xargs -I{} echo "UNCONFIGURED_REPO definitions in review_skip_comments.py: {}"'

uvx showboat verify "$DEMO_FILE"
