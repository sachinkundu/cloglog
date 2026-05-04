---
verdict: no_demo
diff_hash: 68ce5a1d7879772887cc73eece8d7259682815e90ab1ecbfa504e0ec851b5f9b
classifier: demo-classifier
generated_at: 2026-05-04T07:16:06Z
---

## Why no demo

The diff adds NUL-byte sanitization infrastructure (NulSanitizedModel, strip_nul) applied to existing Pydantic write schemas across board/agent/document contexts, a DBAPIError catch-and-log path in review_loop.py with best-effort set_outcome, and a new DB column (outcome) on pr_review_turns. No HTTP route shape, API response, or frontend component changes — endpoints remain identical, only internal validation and error handling change. The outcome column is plumbing for a T-409 badge that does not exist in this diff.

## Changed files

- src/agent/schemas.py
- src/alembic/versions/479ae109c254_add_outcome_to_pr_review_turns.py
- src/board/schemas.py
- src/document/schemas.py
- src/gateway/review_loop.py
- src/review/interfaces.py
- src/review/models.py
- src/review/repository.py
- src/shared/text.py
- tests/board/test_task_create_sanitization.py
- tests/gateway/test_review_loop.py
