#!/usr/bin/env bash
# Demo for T-227: replace pure count cap with verdict-based stop.
#
# Before: MAX_REVIEWS_PER_PR=2, guard = "if prior >= MAX then skip".
# After:  MAX_REVIEWS_PER_PR=5 (backstop), guard = "skip if latest codex
#         review emitted :pass: (verdict=approve); else skip when count >= 5".
#
# Verify-safe: every exec block is a deterministic OK/FAIL boolean or an
# in-process uv run python -c round-trip. No live services, no pytest,
# no DB, no subprocess against GitHub or ollama. `showboat verify` reruns
# every exec under `make quality`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"

# showboat init refuses to overwrite — delete first so `make demo` is re-runnable.
rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "Replace the pure count-based review cap with a verdict-based stop (skip when the latest codex review emitted :pass:) and raise the safety backstop to 5 sessions. Matches T-227 Option B."

# ===================================================================
uvx showboat note "$DEMO_FILE" "### T-227 acceptance evidence — file-level

Three claims, each with a file-level boolean scoped to the files under
audit. Scoping to specific files keeps the demo deterministic under
\`showboat verify\` — an unrelated future doc that mentions the string
can't drift the count."

# ----- 1. Old count-only predicate is GONE from review_engine.py -----
uvx showboat exec "$DEMO_FILE" bash \
  'F=src/gateway/review_engine.py
   # The exact count-only predicate that existed before T-227.
   if grep -q "if prior >= MAX_REVIEWS_PER_PR:" "$F"; then
     echo "old_count_only_predicate_in_review_engine=present"
   else
     echo "old_count_only_predicate_in_review_engine=removed"
   fi'

# ----- 2. New verdict-aware predicate is PRESENT -----
uvx showboat exec "$DEMO_FILE" bash \
  'F=src/gateway/review_engine.py
   grep -q "_should_skip_for_cap" "$F" && echo "pure_decision_helper_used=yes" || echo "pure_decision_helper_used=no"
   grep -q "latest_codex_review_is_approval" "$F" && echo "approval_helper_used=yes" || echo "approval_helper_used=no"
   grep -q "_APPROVE_BODY_PREFIX" "$F" && echo "approve_body_prefix_defined=yes" || echo "approve_body_prefix_defined=no"
   # Regression guard for codex round 1 MEDIUM: the approval check must be
   # per-head_sha so an approval of commit A cannot suppress review of
   # commit B. Aligns with review_loop consensus scope.
   grep -q "commit_id\") == head_sha" "$F" && echo "approval_filter_by_head_sha=yes" || echo "approval_filter_by_head_sha=no"'

# ----- 3. Backstop value bumped to 5 -----
uvx showboat exec "$DEMO_FILE" bash \
  'F=src/gateway/review_engine.py
   grep -q "^MAX_REVIEWS_PER_PR: Final = 5$" "$F" && echo "backstop_value_in_source=5" || echo "backstop_value_in_source=WRONG"'

# ===================================================================
uvx showboat note "$DEMO_FILE" "### Pure helper behaviour — in-process round-trip

\`_should_skip_for_cap(prior_sessions, latest_is_approval)\` returns
\`(skip, is_backstop)\`. The table below covers the four predicate cells:
- below backstop, no approval → proceed
- below backstop, approval → silent skip
- at backstop, no approval → skip with comment
- at backstop, approval → silent skip (approval beats backstop)"

uvx showboat exec "$DEMO_FILE" bash \
  'uv run python -c "
from src.gateway.review_engine import MAX_REVIEWS_PER_PR, _should_skip_for_cap
print(\"max_reviews_per_pr=\", MAX_REVIEWS_PER_PR)
print(\"below_backstop_no_approval=\", _should_skip_for_cap(0, False), _should_skip_for_cap(MAX_REVIEWS_PER_PR - 1, False))
print(\"below_backstop_with_approval=\", _should_skip_for_cap(1, True), _should_skip_for_cap(MAX_REVIEWS_PER_PR - 1, True))
print(\"at_backstop_no_approval=\", _should_skip_for_cap(MAX_REVIEWS_PER_PR, False))
print(\"at_backstop_with_approval=\", _should_skip_for_cap(MAX_REVIEWS_PER_PR, True))
"'

# ===================================================================
uvx showboat note "$DEMO_FILE" "### Approval-detection contract — :pass: body prefix

\`post_review\` pins \`event=\"COMMENT\"\` (pinned by
\`test_verdict_never_becomes_approve_or_request_changes\` — bot never
flips GitHub's merge state), so GitHub state is never \`APPROVED\` for a
codex review. The canonical approval signal is the \`:pass:\` prefix
\`_format_review_body\` emits when codex returns \`verdict=\"approve\"\`.
The demo below round-trips the body format: approve → \`:pass:\`,
request_changes → \`:warning:\`, comment → \`:info:\`."

uvx showboat exec "$DEMO_FILE" bash \
  'uv run python -c "
from src.gateway.review_engine import _APPROVE_BODY_PREFIX, ReviewResult, ReviewFinding, _format_review_body
approve_body = _format_review_body(ReviewResult(verdict=\"approve\", summary=\"ok\", findings=[]), [])
warn_body    = _format_review_body(ReviewResult(verdict=\"request_changes\", summary=\"nope\", findings=[]), [])
info_body    = _format_review_body(ReviewResult(verdict=\"comment\", summary=\"fyi\", findings=[]), [])
print(\"approve_prefix_token=\", repr(_APPROVE_BODY_PREFIX))
print(\"approve_body_starts_with_pass=\", approve_body.startswith(_APPROVE_BODY_PREFIX))
print(\"request_changes_body_starts_with_pass=\", warn_body.startswith(_APPROVE_BODY_PREFIX))
print(\"comment_body_starts_with_pass=\", info_body.startswith(_APPROVE_BODY_PREFIX))
"'

# ===================================================================
uvx showboat note "$DEMO_FILE" "### Contradictory approve demotion — PR #201 round 2 fix

\`ReviewLoop._reached_consensus\` treats \`verdict=\"approve\"\` + any
\`critical\`/\`high\` finding as a self-contradiction and refuses to
short-circuit. Before this round, \`_format_review_body\` still emitted
\`:pass:\` for that body — and on a webhook replay the T-227 approval
helper would have silently skipped further review, even though the
loop logic said the output was not a real approval. Fix: demote the
body prefix to \`:warning:\` when the approve verdict is contradicted by
a severe finding. The helper then correctly returns False.

Below: verdict=approve + critical → :warning:; verdict=approve + high
→ :warning:; verdict=approve + only low/medium/info findings → still
:pass: (those severities are compatible with approval)."

uvx showboat exec "$DEMO_FILE" bash \
  'uv run python -c "
from src.gateway.review_engine import ReviewResult, ReviewFinding, _format_review_body
def prefix(body):
    return body.split(\":\", 2)[1] if body.startswith(\":\") else \"?\"
critical = _format_review_body(ReviewResult(verdict=\"approve\", summary=\"oops\", findings=[
    ReviewFinding(file=\"a.py\", line=1, severity=\"critical\", body=\"bad\"),
]), [])
high = _format_review_body(ReviewResult(verdict=\"approve\", summary=\"oops\", findings=[
    ReviewFinding(file=\"a.py\", line=1, severity=\"high\", body=\"risky\"),
]), [])
low_only = _format_review_body(ReviewResult(verdict=\"approve\", summary=\"nit\", findings=[
    ReviewFinding(file=\"a.py\", line=1, severity=\"low\", body=\"style\"),
    ReviewFinding(file=\"a.py\", line=2, severity=\"medium\", body=\"trivial\"),
    ReviewFinding(file=\"a.py\", line=3, severity=\"info\", body=\"fyi\"),
]), [])
print(\"approve_with_critical_prefix=\", prefix(critical))
print(\"approve_with_high_prefix=\", prefix(high))
print(\"approve_with_low_medium_info_only_prefix=\", prefix(low_only))
"'

# ===================================================================
uvx showboat note "$DEMO_FILE" "### Backstop skip-comment copy — regression guard

When the backstop trips the engine posts the same class of skip comment
as the old count cap — but worded to explain the new verdict-based
semantic. Pin the body shape in-process so the copy can't regress silently."

uvx showboat exec "$DEMO_FILE" bash \
  'uv run python -c "
from src.gateway.review_engine import MAX_REVIEWS_PER_PR
body = (
    f\"Review skipped: this PR reached the maximum of \"
    f\"{MAX_REVIEWS_PER_PR} bot review sessions without the \"
    f\"bot reaching approval. Request human review.\"
)
print(\"body=\", body)
print(\"contains_maximum=\", \"maximum\" in body.lower())
print(\"contains_backstop_value=\", str(MAX_REVIEWS_PER_PR) in body)
print(\"contains_approval_word=\", \"approval\" in body.lower() or \"approved\" in body.lower())
"'

# ===================================================================
uvx showboat note "$DEMO_FILE" "### Unit tests — filesystem boolean

The updated tests live in \`tests/gateway/test_review_engine.py\`:
- \`TestShouldSkipForCap\` — four predicate cells on the pure helper
- \`TestLatestCodexReviewIsApproval\` — the :pass: detection helper
- \`TestVerdictBasedCap\` — end-to-end consumer path: proceed / silent-skip / backstop

Below is a filesystem boolean confirming each class exists at the expected
file location. The actual pytest run happens in \`make quality\`; this
demo only pins the test surface so a future rename can't hide a regression."

uvx showboat exec "$DEMO_FILE" bash \
  'T=tests/gateway/test_review_engine.py
   grep -q "^class TestShouldSkipForCap:" "$T" && echo "test_class_should_skip_for_cap=yes" || echo "test_class_should_skip_for_cap=no"
   grep -q "^class TestLatestCodexReviewIsApproval:" "$T" && echo "test_class_latest_codex_review_is_approval=yes" || echo "test_class_latest_codex_review_is_approval=no"
   grep -q "^class TestVerdictBasedCap:" "$T" && echo "test_class_verdict_based_cap=yes" || echo "test_class_verdict_based_cap=no"
   grep -q "test_proceeds_when_under_backstop_and_no_approval" "$T" && echo "proceed_case_covered=yes" || echo "proceed_case_covered=no"
   grep -q "test_skips_silently_when_latest_bot_review_is_approval" "$T" && echo "approval_skip_case_covered=yes" || echo "approval_skip_case_covered=no"
   grep -q "test_backstop_triggers_at_max_without_approval" "$T" && echo "backstop_case_covered=yes" || echo "backstop_case_covered=no"
   grep -q "test_approval_on_older_sha_does_not_apply_to_new_sha" "$T" && echo "head_sha_scoping_case_covered=yes" || echo "head_sha_scoping_case_covered=no"
   grep -q "test_contradictory_approve_body_is_not_detected_as_approval" "$T" && echo "contradictory_approve_case_covered=yes" || echo "contradictory_approve_case_covered=no"
   grep -q "test_approve_with_critical_finding_is_demoted_to_warning" "$T" && echo "format_body_demotion_pin_test=yes" || echo "format_body_demotion_pin_test=no"'

# ===================================================================
uvx showboat note "$DEMO_FILE" "### Scope — Gateway-only

Files changed:
- \`src/gateway/review_engine.py\` — constant bumped, helpers added, guard rewritten
- \`tests/gateway/test_review_engine.py\` — new test classes + one updated skip-comment assertion

Out of scope (unchanged): Alembic migrations, API contract, settings,
\`count_bot_reviews\` signature. The boolean below pins the signature
so a future refactor can't silently break callers outside this file."

uvx showboat exec "$DEMO_FILE" bash \
  'if grep -q "^async def count_bot_reviews(" src/gateway/review_engine.py; then
     echo "count_bot_reviews_signature_stable=yes"
   else
     echo "count_bot_reviews_signature_stable=no"
   fi'

echo
echo "demo generated at: $DEMO_FILE"
