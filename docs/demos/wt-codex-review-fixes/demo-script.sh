#!/usr/bin/env bash
# Demo: T-376 — codex review cap counts posted reviews, not session attempts.
# Called by `make demo` (server + DB up). Pure-Python proof — no webhooks.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"

rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "PR-review cap counts POSTED codex reviews (not session attempts) so non-post terminals — rate-limit skip, codex_unavailable, post_failed — don't consume the 5-review budget."

# ----- Before: pre-T-376, the cap counted via count_bot_reviews (GitHub side).
uvx showboat note "$DEMO_FILE" \
  "Before T-376: the cap source was indirect (GitHub /reviews list). Cap-key wiring lived at src/gateway/review_engine.py: 'prior = await count_bot_reviews(...)'. A non-post terminal happened to leave no GitHub review, but the count source made the 'session N/5' counter incongruent with what readers actually saw on the PR."

# ----- Action: drive the new registry helper through three scenarios on the
# same FakeRegistry the loop tests use, so the demo touches the production
# count rule (count_posted_codex_sessions distinct over posted_at NOT NULL).
uvx showboat exec "$DEMO_FILE" bash 'uv run --quiet python - <<PY
import asyncio, sys, uuid
sys.path.insert(0, "tests")
from gateway.test_review_loop import FakeRegistry  # noqa: E402

async def main() -> None:
    pr = "https://github.com/sachinkundu/cloglog/pull/376"
    project_id = uuid.uuid4()

    async def claim(reg, sha, session_index):
        await reg.claim_turn(
            project_id=project_id, pr_url=pr, pr_number=376,
            head_sha=sha, stage="codex", turn_number=1,
            session_index=session_index,
        )

    async def post(reg, sha):
        await reg.mark_posted(pr_url=pr, head_sha=sha, stage="codex", turn_number=1)

    # --- Scenario A: 5 sessions, 3 post and 2 are non-post terminals.
    # Pre-T-376 the cap would have read the session-attempt count (5) and
    # blocked the 4th try. T-376 reads posted_at and lets the budget keep
    # ticking until 5 reviews actually land.
    a = FakeRegistry()
    for s, suffix in ((1, "aaa"), (2, "bbb"), (3, "ccc")):
        sha = ("0" * 40)[: 40 - len(suffix)] + suffix
        await claim(a, sha, s)
        await post(a, sha)
    for s, suffix in ((4, "ddd"), (5, "eee")):  # non-post terminals
        sha = ("0" * 40)[: 40 - len(suffix)] + suffix
        await claim(a, sha, s)
    cap_a = await a.count_posted_codex_sessions(pr_url=pr)
    assert cap_a == 3, f"scenario A: expected 3 posted, got {cap_a}"

    # --- Scenario B: 5 successful posts → cap reads 5 → next session refused.
    b = FakeRegistry()
    for s, suffix in ((1, "f01"), (2, "f02"), (3, "f03"), (4, "f04"), (5, "f05")):
        sha = ("0" * 40)[: 40 - len(suffix)] + suffix
        await claim(b, sha, s)
        await post(b, sha)
    cap_b = await b.count_posted_codex_sessions(pr_url=pr)
    assert cap_b == 5, f"scenario B: expected 5 posted, got {cap_b}"

    # --- Scenario C: multi-turn within one session (codex_max_turns > 1) —
    # both turns post successfully; cap counts the SESSION once, not each
    # POST. Per-turn POST contract (two-stage-pr-review.md §3.3) preserved.
    c = FakeRegistry()
    sha = "c" * 40
    for turn in (1, 2):
        await c.claim_turn(
            project_id=project_id, pr_url=pr, pr_number=376,
            head_sha=sha, stage="codex", turn_number=turn,
            session_index=7,
        )
        await c.mark_posted(pr_url=pr, head_sha=sha, stage="codex", turn_number=turn)
    cap_c = await c.count_posted_codex_sessions(pr_url=pr)
    assert cap_c == 1, f"scenario C: expected 1 (multi-turn collapses), got {cap_c}"

    print(f"A 3posts+2nonpost cap={cap_a}/5 (4th allowed)")
    print(f"B 5posts            cap={cap_b}/5 (6th BLOCKED)")
    print(f"C 1session 2turns   cap={cap_c}/5 (multi-turn collapses)")

asyncio.run(main())
PY'

# ----- After: the engine-level skip-comment path also reads the registry.
# Pin the body header docstring still calls out post-number semantics so
# a future reader doesn't regress to "session-attempt" counting.
uvx showboat note "$DEMO_FILE" \
  "After T-376: the cap reads count_posted_codex_sessions and the body header value reflects post number. The wording stays 'session N/5' for back-compat with PRs that already carry the older header — the value is what changed."

uvx showboat exec "$DEMO_FILE" bash \
  'echo "header value source: $(grep -c "count_posted_codex_sessions" src/gateway/review_engine.py) call(s) in review_engine.py"'

uvx showboat exec "$DEMO_FILE" bash \
  'echo "registry method: $(grep -c "count_posted_codex_sessions" src/review/repository.py) impl in repository.py"'

# ----- Engine cap pin tests run via direct import (not pytest, so the
# session-autouse Postgres fixture in tests/conftest.py does NOT fire and
# `showboat verify` works on a clean host). Using the FakeRegistry path
# keeps it fully in-process.
uvx showboat exec "$DEMO_FILE" bash 'uv run --quiet python - <<PY
import asyncio, sys
sys.path.insert(0, "tests")
from gateway.test_review_engine import TestT376PostedCountCap  # noqa: E402

# Minimal sample diff (matches the sample_diff fixture used in pytest).
sample = "diff --git a/src/x.py b/src/x.py\n--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-a\n+b\n"

t = TestT376PostedCountCap()
asyncio.run(t.test_three_posts_five_attempts_cap_does_not_fire(sample))
asyncio.run(t.test_five_posts_blocks_sixth_session(sample))
print("2 engine-level cap pins passed")
PY'

uvx showboat verify "$DEMO_FILE"
