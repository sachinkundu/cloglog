#!/usr/bin/env bash
# Demo: Operators can now see a discriminated codex-review badge on each Kanban
# task card — working / N of M / pass / exhausted / failed / stale — instead of
# just a binary "codex reviewed" boolean.
#
# Called by make demo (server + DB already running).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../scripts/worktree-ports.sh"

DASHBOARD_KEY=$(grep '^dashboard_key:' "$(git rev-parse --show-toplevel)/.cloglog/config.yaml" \
                | head -n1 | sed 's/^dashboard_key:[[:space:]]*//' \
                | sed 's/[[:space:]]*#.*$//' | tr -d '"'"'")

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_FILE="docs/demos/${BRANCH//\//-}/demo.md"
BASE="http://localhost:${BACKEND_PORT}/api/v1"

rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "Operators can now see a discriminated codex-review badge on each Kanban task card — working / N of M / pass / exhausted / stale — instead of just a binary reviewed boolean."

# ── 1. New CodexStatus enum ──────────────────────────────────────────────────
uvx showboat note "$DEMO_FILE" \
  "New CodexStatus enum in src/review/interfaces.py — seven states replace the old 'touched' boolean"
uvx showboat exec "$DEMO_FILE" bash \
  'grep -A10 "class CodexStatus" src/review/interfaces.py | grep -v "^--"'

# ── 2. New board schema fields ───────────────────────────────────────────────
uvx showboat note "$DEMO_FILE" \
  "Board API schema (src/board/schemas.py) now carries codex_status and codex_progress alongside the deprecated boolean"
uvx showboat exec "$DEMO_FILE" bash \
  'grep -E "codex_status|codex_progress|codex_review_picked_up" src/board/schemas.py'

# ── 3. Pure-function projection proof ────────────────────────────────────────
uvx showboat note "$DEMO_FILE" \
  "ReviewTurnRepository._derive_codex_status is a pure static function — no DB needed to verify all 7 states"
uvx showboat exec "$DEMO_FILE" bash \
  'uv run --quiet python - <<'"'"'PY'"'"'
from types import SimpleNamespace
from src.review.repository import ReviewTurnRepository

SHA = "a" * 40
NEW_SHA = "b" * 40

def turn(sha, status, consensus=False, turn_number=1):
    return SimpleNamespace(
        head_sha=sha, status=status, consensus_reached=consensus, turn_number=turn_number
    )

cases = [
    ("NOT_STARTED - no turns",    [], SHA,     1, "not_started"),
    ("NOT_STARTED - empty sha",   [], "",      1, "not_started"),
    ("WORKING     - running turn", [turn(SHA, "running")], SHA, 1, "working"),
    ("PASS        - consensus",    [turn(SHA, "completed", True)], SHA, 1, "pass"),
    ("EXHAUSTED   - 3/3 no-cons",  [turn(SHA,"completed",False,i) for i in range(1,4)], SHA, 3, "exhausted"),
    ("FAILED      - timed_out",    [turn(SHA, "timed_out")], SHA, 1, "failed"),
    ("PROGRESS    - 1/3",          [turn(SHA, "completed", False)], SHA, 3, "progress"),
    ("STALE       - new sha",      [turn(SHA, "completed", True)], NEW_SHA, 1, "stale"),
]

all_ok = True
for label, turns, sha, max_t, expected in cases:
    result = ReviewTurnRepository._derive_codex_status(turns, sha, max_t)
    ok = result.status.value == expected
    all_ok = all_ok and ok
    marker = "OK" if ok else "FAIL"
    print("  %s %s -> %s" % (marker, label, result.status.value))

suffix = "states verified OK" if all_ok else "FAILURE: some states incorrect"
print("%d %s" % (len(cases), suffix))
PY'

# ── 4. API contract pin ──────────────────────────────────────────────────────
uvx showboat note "$DEMO_FILE" \
  "Pin test: board API contract carries codex_status, codex_progress, and codex_review_picked_up on TaskCard"
uvx showboat exec "$DEMO_FILE" bash \
  'uv run --quiet python - <<'"'"'PY'"'"'
import ast, sys
tree = ast.parse(open("src/board/schemas.py").read())
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == "TaskCard":
        fields = []
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                name = stmt.target.id
                if name.startswith("codex"):
                    fields.append(name)
        print("TaskCard codex fields: " + ", ".join(fields))
        break
PY'

# ── 5. Webhook consumer now tracks pr_head_sha ───────────────────────────────
uvx showboat note "$DEMO_FILE" \
  "Webhook consumer updates pr_head_sha on PR_OPENED and PR_SYNCHRONIZE so the board can project accurate status"
uvx showboat exec "$DEMO_FILE" bash \
  'grep -E "PR_OPENED|PR_SYNCHRONIZE|pr_head_sha" src/gateway/webhook_consumers.py | head -8'

uvx showboat verify "$DEMO_FILE"
