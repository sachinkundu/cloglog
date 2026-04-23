#!/usr/bin/env bash
# Demo: Opencode reviewer now reads the codebase instead of scanning the
# diff in --pure mode, so its verdicts come from real verification instead
# of defaulting to pass.
# Called by make demo (server + DB already running, but this demo needs
# neither — it is pure filesystem + in-process parse assertions).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_FILE="docs/demos/${BRANCH//\//-}/demo.md"

PROMPT_FILE=".github/opencode/prompts/review.md"
LOOP_FILE="src/gateway/review_loop.py"

rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "Opencode reviewer now reads the codebase during review — deep-verification framing replaces first-pass framing and --pure is gone, so verdicts reflect real checks instead of defaulting to pass."

# ---------------------------------------------------------------------------
# Piece 1 — prompt rewrite. File-scoped booleans only.
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Piece 1 — .github/opencode/prompts/review.md carries the deep-verification framing."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "deep verification review" "'"$PROMPT_FILE"'" && echo OK || echo FAIL'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "FULL ACCESS to the project filesystem" "'"$PROMPT_FILE"'" && echo OK || echo FAIL'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "evidence from a file you read outside the diff" "'"$PROMPT_FILE"'" && echo OK || echo FAIL'

uvx showboat note "$DEMO_FILE" \
  "The old pass-biasing framing is gone from the same file."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -iq "first-pass" "'"$PROMPT_FILE"'" && echo PRESENT || echo ABSENT'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -iq "cheap checks" "'"$PROMPT_FILE"'" && echo PRESENT || echo ABSENT'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -iq "leave deep architectural judgement for the cloud reviewer" "'"$PROMPT_FILE"'" && echo PRESENT || echo ABSENT'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -iq "on turn 1 specifically" "'"$PROMPT_FILE"'" && echo PRESENT || echo ABSENT'

uvx showboat note "$DEMO_FILE" \
  "The JSON schema block is preserved verbatim — the sequencer's parser depends on this shape."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "\"overall_correctness\"" "'"$PROMPT_FILE"'" && echo OK || echo FAIL'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "\"no_further_concerns\"" "'"$PROMPT_FILE"'" && echo OK || echo FAIL'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "\"review_in_progress\"" "'"$PROMPT_FILE"'" && echo OK || echo FAIL'

# ---------------------------------------------------------------------------
# Piece 2 — opencode argv no longer passes --pure.
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Piece 2 — src/gateway/review_loop.py no longer passes --pure to the opencode CLI, but still passes --dangerously-skip-permissions so opencode does not prompt."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q -- "\"--pure\"" "'"$LOOP_FILE"'" && echo PRESENT || echo ABSENT'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q -- "\"--dangerously-skip-permissions\"" "'"$LOOP_FILE"'" && echo OK || echo FAIL'

# ---------------------------------------------------------------------------
# Parse-through — the new prompt's schema still round-trips through
# parse_reviewer_output. This is the sanity check that piece 1 did not
# accidentally break the sequencer's JSON contract.
#
# python3 -c, NOT `uv run pytest` — conftest's session-autouse Postgres
# fixture fails under `uvx showboat verify`, which runs on a clean host
# with no DB. A direct import bypasses conftest.
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Parse-through — an example JSON payload matching the new prompt's schema round-trips through parse_reviewer_output and yields the expected verdict."
uvx showboat exec "$DEMO_FILE" bash \
  'uv run python3 -c "
import json
from src.gateway.review_engine import parse_reviewer_output

approve_payload = json.dumps({
    \"findings\": [],
    \"overall_correctness\": \"patch is correct\",
    \"overall_explanation\": \"verified against fs.\",
    \"overall_confidence_score\": 0.9,
    \"status\": \"no_further_concerns\",
})
result = parse_reviewer_output(approve_payload)
assert result is not None, \"approve payload did not parse\"
assert result.verdict == \"approve\", result.verdict

reject_payload = json.dumps({
    \"findings\": [
        {
            \"title\": \"missing guard\",
            \"body\": \"exploitable.\",
            \"confidence_score\": 0.9,
            \"priority\": 3,
            \"code_location\": {
                \"absolute_file_path\": \"src/x.py\",
                \"line_range\": {\"start\": 1, \"end\": 2},
            },
        }
    ],
    \"overall_correctness\": \"patch is incorrect\",
    \"overall_explanation\": \"critical gap.\",
    \"overall_confidence_score\": 0.95,
    \"status\": \"review_in_progress\",
})
result2 = parse_reviewer_output(reject_payload)
assert result2 is not None, \"reject payload did not parse\"
assert result2.verdict == \"request_changes\", result2.verdict
print(\"2 parse assertions passed\")
"'

uvx showboat verify "$DEMO_FILE"
