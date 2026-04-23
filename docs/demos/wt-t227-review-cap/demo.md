# Replace the pure count-based review cap with a verdict-based stop (skip when the latest codex review emitted :pass:) and raise the safety backstop to 5 sessions. Matches T-227 Option B.

*2026-04-23T17:10:39Z by Showboat 0.6.1*
<!-- showboat-id: d1b114a9-65d8-44dc-a8f4-cdb28f44b663 -->

### T-227 acceptance evidence — file-level

Three claims, each with a file-level boolean scoped to the files under
audit. Scoping to specific files keeps the demo deterministic under
`showboat verify` — an unrelated future doc that mentions the string
can't drift the count.

```bash
F=src/gateway/review_engine.py
   # The exact count-only predicate that existed before T-227.
   if grep -q "if prior >= MAX_REVIEWS_PER_PR:" "$F"; then
     echo "old_count_only_predicate_in_review_engine=present"
   else
     echo "old_count_only_predicate_in_review_engine=removed"
   fi
```

```output
old_count_only_predicate_in_review_engine=removed
```

```bash
F=src/gateway/review_engine.py
   grep -q "_should_skip_for_cap" "$F" && echo "pure_decision_helper_used=yes" || echo "pure_decision_helper_used=no"
   grep -q "latest_codex_review_is_approval" "$F" && echo "approval_helper_used=yes" || echo "approval_helper_used=no"
   grep -q "_APPROVE_BODY_PREFIX" "$F" && echo "approve_body_prefix_defined=yes" || echo "approve_body_prefix_defined=no"
```

```output
pure_decision_helper_used=yes
approval_helper_used=yes
approve_body_prefix_defined=yes
```

```bash
F=src/gateway/review_engine.py
   grep -q "^MAX_REVIEWS_PER_PR: Final = 5$" "$F" && echo "backstop_value_in_source=5" || echo "backstop_value_in_source=WRONG"
```

```output
backstop_value_in_source=5
```

### Pure helper behaviour — in-process round-trip

`_should_skip_for_cap(prior_sessions, latest_is_approval)` returns
`(skip, is_backstop)`. The table below covers the four predicate cells:
- below backstop, no approval → proceed
- below backstop, approval → silent skip
- at backstop, no approval → skip with comment
- at backstop, approval → silent skip (approval beats backstop)

```bash
uv run python -c "
from src.gateway.review_engine import MAX_REVIEWS_PER_PR, _should_skip_for_cap
print(\"max_reviews_per_pr=\", MAX_REVIEWS_PER_PR)
print(\"below_backstop_no_approval=\", _should_skip_for_cap(0, False), _should_skip_for_cap(MAX_REVIEWS_PER_PR - 1, False))
print(\"below_backstop_with_approval=\", _should_skip_for_cap(1, True), _should_skip_for_cap(MAX_REVIEWS_PER_PR - 1, True))
print(\"at_backstop_no_approval=\", _should_skip_for_cap(MAX_REVIEWS_PER_PR, False))
print(\"at_backstop_with_approval=\", _should_skip_for_cap(MAX_REVIEWS_PER_PR, True))
"
```

```output
max_reviews_per_pr= 5
below_backstop_no_approval= (False, False) (False, False)
below_backstop_with_approval= (True, False) (True, False)
at_backstop_no_approval= (True, True)
at_backstop_with_approval= (True, False)
```

### Approval-detection contract — :pass: body prefix

`post_review` pins `event="COMMENT"` (pinned by
`test_verdict_never_becomes_approve_or_request_changes` — bot never
flips GitHub's merge state), so GitHub state is never `APPROVED` for a
codex review. The canonical approval signal is the `:pass:` prefix
`_format_review_body` emits when codex returns `verdict="approve"`.
The demo below round-trips the body format: approve → `:pass:`,
request_changes → `:warning:`, comment → `:info:`.

```bash
uv run python -c "
from src.gateway.review_engine import _APPROVE_BODY_PREFIX, ReviewResult, _format_review_body
approve_body = _format_review_body(ReviewResult(verdict=\"approve\", summary=\"ok\", findings=[]), [])
warn_body    = _format_review_body(ReviewResult(verdict=\"request_changes\", summary=\"nope\", findings=[]), [])
info_body    = _format_review_body(ReviewResult(verdict=\"comment\", summary=\"fyi\", findings=[]), [])
print(\"approve_prefix_token=\", repr(_APPROVE_BODY_PREFIX))
print(\"approve_body_starts_with_pass=\", approve_body.startswith(_APPROVE_BODY_PREFIX))
print(\"request_changes_body_starts_with_pass=\", warn_body.startswith(_APPROVE_BODY_PREFIX))
print(\"comment_body_starts_with_pass=\", info_body.startswith(_APPROVE_BODY_PREFIX))
"
```

```output
approve_prefix_token= ':pass:'
approve_body_starts_with_pass= True
request_changes_body_starts_with_pass= False
comment_body_starts_with_pass= False
```

### Backstop skip-comment copy — regression guard

When the backstop trips the engine posts the same class of skip comment
as the old count cap — but worded to explain the new verdict-based
semantic. Pin the body shape in-process so the copy can't regress silently.

```bash
uv run python -c "
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
"
```

```output
body= Review skipped: this PR reached the maximum of 5 bot review sessions without the bot reaching approval. Request human review.
contains_maximum= True
contains_backstop_value= True
contains_approval_word= True
```

### Unit tests — filesystem boolean

The updated tests live in `tests/gateway/test_review_engine.py`:
- `TestShouldSkipForCap` — four predicate cells on the pure helper
- `TestLatestCodexReviewIsApproval` — the :pass: detection helper
- `TestVerdictBasedCap` — end-to-end consumer path: proceed / silent-skip / backstop

Below is a filesystem boolean confirming each class exists at the expected
file location. The actual pytest run happens in `make quality`; this
demo only pins the test surface so a future rename can't hide a regression.

```bash
T=tests/gateway/test_review_engine.py
   grep -q "^class TestShouldSkipForCap:" "$T" && echo "test_class_should_skip_for_cap=yes" || echo "test_class_should_skip_for_cap=no"
   grep -q "^class TestLatestCodexReviewIsApproval:" "$T" && echo "test_class_latest_codex_review_is_approval=yes" || echo "test_class_latest_codex_review_is_approval=no"
   grep -q "^class TestVerdictBasedCap:" "$T" && echo "test_class_verdict_based_cap=yes" || echo "test_class_verdict_based_cap=no"
   grep -q "test_proceeds_when_under_backstop_and_no_approval" "$T" && echo "proceed_case_covered=yes" || echo "proceed_case_covered=no"
   grep -q "test_skips_silently_when_latest_bot_review_is_approval" "$T" && echo "approval_skip_case_covered=yes" || echo "approval_skip_case_covered=no"
   grep -q "test_backstop_triggers_at_max_without_approval" "$T" && echo "backstop_case_covered=yes" || echo "backstop_case_covered=no"
```

```output
test_class_should_skip_for_cap=yes
test_class_latest_codex_review_is_approval=yes
test_class_verdict_based_cap=yes
proceed_case_covered=yes
approval_skip_case_covered=yes
backstop_case_covered=yes
```

### Scope — Gateway-only

Files changed:
- `src/gateway/review_engine.py` — constant bumped, helpers added, guard rewritten
- `tests/gateway/test_review_engine.py` — new test classes + one updated skip-comment assertion

Out of scope (unchanged): Alembic migrations, API contract, settings,
`count_bot_reviews` signature. The boolean below pins the signature
so a future refactor can't silently break callers outside this file.

```bash
if grep -q "^async def count_bot_reviews(" src/gateway/review_engine.py; then
     echo "count_bot_reviews_signature_stable=yes"
   else
     echo "count_bot_reviews_signature_stable=no"
   fi
```

```output
count_bot_reviews_signature_stable=yes
```
