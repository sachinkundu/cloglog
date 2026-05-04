#!/usr/bin/env bash
# Demo: rate-limit-skip path now schedules a real retry instead of posting
# a "Will retry after ~N minutes" comment that never comes.
# Called by `make demo`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"

rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "When the PR-review webhook hits the rate limit, the bot now schedules a real follow-up review after the wait window — the 'Will retry after ~N minutes' comment is no longer a lie."

uvx showboat note "$DEMO_FILE" \
  "Before T-381: ReviewEngineConsumer.handle() short-circuited on rate-limit, posted the 'Will retry' skip comment, and returned. No timer, no queue — the PR sat silent until a new commit was pushed."
uvx showboat exec "$DEMO_FILE" bash \
  'echo "retry-scheduling references on main HEAD before T-381: $(git show c1c09121b593fd3576a3b3bd70278202354b16a1:src/gateway/review_engine.py | grep -cE "asyncio\.create_task|_schedule_rate_limit_retry" || true)"'

uvx showboat note "$DEMO_FILE" \
  "After T-381: the skip path schedules an asyncio.Task that sleeps for the rate-limiter window and then re-invokes _review_pr. The skip-comment promise is now backed by code."
uvx showboat exec "$DEMO_FILE" bash \
  'echo "_schedule_rate_limit_retry references in this branch: $(grep -c _schedule_rate_limit_retry src/gateway/review_engine.py)"'

uvx showboat note "$DEMO_FILE" \
  "Pin tests in TestRateLimitRetry exercise the property end-to-end: rate-limit triggers handle() → a Task lands in _pending_retries → fast-forwarded sleep → _review_pr is invoked with the original event. A second push during the wait cancels the older retry and replaces it."
uvx showboat exec "$DEMO_FILE" bash \
  'uv run --quiet python - <<PY
import asyncio, sys
sys.path.insert(0, "tests")
from gateway import test_review_engine as t
cases = [
    t.TestRateLimitRetry().test_handle_schedules_real_retry_task,
    t.TestRateLimitRetry().test_retry_task_invokes_review_pr_after_wait,
    t.TestRateLimitRetry().test_second_push_during_window_replaces_pending_retry,
]
for case in cases:
    asyncio.run(case())
print(f"{len(cases)} pin assertions passed")
PY'

uvx showboat verify "$DEMO_FILE"
