#!/usr/bin/env bash
# Demo: T-424 — EXHAUSTED badge fires only after PR-wide MAX_REVIEWS_PER_PR cap,
# not after the first per-session non-consensus turn (codex_max_turns=1).
# Called by `make demo` (server + DB already running).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"
DEMO_FILE="$SCRIPT_DIR/demo.md"

rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "EXHAUSTED badge no longer fires after the first non-consensus codex turn — it now waits for the PR-wide MAX_REVIEWS_PER_PR=5 cap, matching the actual review-loop semantics."

uvx showboat note "$DEMO_FILE" \
  "Before T-424: \`_derive_codex_status\` keyed EXHAUSTED on the per-session \`codex_max_turns\` (default 1). One completed non-consensus turn → EXHAUSTED, even though four more review sessions were still permitted on later pushes."

uvx showboat note "$DEMO_FILE" \
  "After T-424: gating uses the PR-wide distinct posted \`session_index\` count and the new \`max_pr_sessions\` argument (\`MAX_REVIEWS_PER_PR=5\`). EXHAUSTED only fires when five posted sessions all closed without consensus."

uvx showboat note "$DEMO_FILE" \
  "Scenario 1 — single posted non-consensus session (the previously-buggy case): expect PROGRESS."

uvx showboat exec "$DEMO_FILE" bash 'cd "$(git rev-parse --show-toplevel)" && uv run --quiet python - <<PY
from datetime import UTC, datetime
from src.review.repository import ReviewTurnRepository
from src.review.models import PrReviewTurn
from src.review.interfaces import CodexStatus, MAX_REVIEWS_PER_PR

sha = "a" * 40
turns = [
    PrReviewTurn(
        pr_url="https://github.com/o/r/pull/424",
        pr_number=424,
        head_sha=sha,
        stage="codex",
        turn_number=1,
        status="completed",
        consensus_reached=False,
        session_index=1,
        posted_at=datetime.now(UTC),
    )
]
result = ReviewTurnRepository._derive_codex_status(
    turns, sha, max_turns=1, max_pr_sessions=MAX_REVIEWS_PER_PR
)
print(f"max_pr_sessions={MAX_REVIEWS_PER_PR}")
print(f"posted_sessions=1")
print(f"status={result.status.value}")
assert result.status == CodexStatus.PROGRESS, result.status
print("OK: PROGRESS (not EXHAUSTED) — pre-fix this returned EXHAUSTED")
PY'

uvx showboat note "$DEMO_FILE" \
  "Scenario 2 — five distinct posted non-consensus sessions (cap reached): expect EXHAUSTED."

uvx showboat exec "$DEMO_FILE" bash 'cd "$(git rev-parse --show-toplevel)" && uv run --quiet python - <<PY
from datetime import UTC, datetime
from src.review.repository import ReviewTurnRepository
from src.review.models import PrReviewTurn
from src.review.interfaces import CodexStatus, MAX_REVIEWS_PER_PR

sha = "b" * 40
posted = datetime.now(UTC)
turns = [
    PrReviewTurn(
        pr_url="https://github.com/o/r/pull/424b",
        pr_number=424,
        head_sha=sha,
        stage="codex",
        turn_number=i,
        status="completed",
        consensus_reached=False,
        session_index=i,
        posted_at=posted,
    )
    for i in range(1, 6)
]
result = ReviewTurnRepository._derive_codex_status(
    turns, sha, max_turns=1, max_pr_sessions=MAX_REVIEWS_PER_PR
)
print(f"max_pr_sessions={MAX_REVIEWS_PER_PR}")
print(f"posted_sessions=5")
print(f"status={result.status.value}")
assert result.status == CodexStatus.EXHAUSTED, result.status
print("OK: EXHAUSTED (cap reached)")
PY'

uvx showboat note "$DEMO_FILE" \
  "Scenario 3 — pre-T-375 rows (\`session_index IS NULL\`, \`posted_at IS NULL\`) do not count toward the cap, even when there are seven of them. Mirrors \`count_posted_codex_sessions\` semantics."

uvx showboat exec "$DEMO_FILE" bash 'cd "$(git rev-parse --show-toplevel)" && uv run --quiet python - <<PY
from src.review.repository import ReviewTurnRepository
from src.review.models import PrReviewTurn
from src.review.interfaces import CodexStatus, MAX_REVIEWS_PER_PR

sha = "c" * 40
turns = [
    PrReviewTurn(
        pr_url="https://github.com/o/r/pull/424c",
        pr_number=4240,
        head_sha=sha,
        stage="codex",
        turn_number=i,
        status="completed",
        consensus_reached=False,
        session_index=None,
        posted_at=None,
    )
    for i in range(1, 8)
]
result = ReviewTurnRepository._derive_codex_status(
    turns, sha, max_turns=1, max_pr_sessions=MAX_REVIEWS_PER_PR
)
print(f"max_pr_sessions={MAX_REVIEWS_PER_PR}")
print(f"posted_sessions=0  # NULL session_index/posted_at do not count")
print(f"status={result.status.value}")
assert result.status == CodexStatus.PROGRESS, result.status
print("OK: PROGRESS (legacy rows ignored)")
PY'

uvx showboat note "$DEMO_FILE" \
  "Pin tests live in \`tests/board/test_codex_status_projection.py\` (\`test_progress_when_pr_session_cap_not_yet_reached\`, \`test_exhausted_pr_wide_session_cap_no_consensus\`, \`test_progress_no_session_index_does_not_count_toward_exhausted\`) and \`tests/board/test_board_review_boundary.py\` (registry signature now requires \`max_pr_sessions\`)."

uvx showboat verify "$DEMO_FILE"
