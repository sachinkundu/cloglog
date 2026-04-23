#!/usr/bin/env bash
# Demo: T-272 HOTFIX — restore --pure in the opencode argv so gemma4-e4b-32k
# emits single-shot JSON instead of narrating tool calls. T-268 removed the
# flag on the wrong hypothesis; PR #194 (2026-04-23) hit live breakage on
# every turn with "opencode output unparseable". This demo proves the argv
# is fixed, the prompt stops claiming filesystem access the model does not
# have, the JSON schema still round-trips through parse_reviewer_output,
# and that `opencode run --pure` emits the expected literal JSON end-to-end.
#
# Called by `make demo`. Needs neither backend nor DB — filesystem greps,
# an in-process parse, and a one-shot opencode invocation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_FILE="docs/demos/${BRANCH//\//-}/demo.md"

PROMPT_FILE=".github/opencode/prompts/review.md"
LOOP_FILE="src/gateway/review_loop.py"

# `uvx showboat init` refuses to overwrite — delete the file so `make demo` is re-runnable.
rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "HOTFIX: --pure is back in the opencode argv so gemma4-e4b-32k emits JSON instead of narrating tool calls, and the prompt no longer claims filesystem access the model does not have under --pure."

# ---------------------------------------------------------------------------
# Piece 1 — --pure is back in the argv (this is the core fix).
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Piece 1 — src/gateway/review_loop.py now passes --pure AND --dangerously-skip-permissions in the opencode argv. --pure disables the default plugin set that gives the model tool access; without it, gemma4-e4b-32k narrates tool calls instead of emitting JSON (observed on PR #194)."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q -- "\"--pure\"" "'"$LOOP_FILE"'" && echo OK || echo FAIL'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q -- "\"--dangerously-skip-permissions\"" "'"$LOOP_FILE"'" && echo OK || echo FAIL'

# ---------------------------------------------------------------------------
# Piece 2 — prompt is now honest about tool access.
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Piece 2 — .github/opencode/prompts/review.md no longer claims filesystem access the model does not have under --pure. The honest 'no tool access' framing replaces 'FULL ACCESS to the project filesystem' and 'evidence from a file you read outside the diff'."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "no tool access" "'"$PROMPT_FILE"'" && echo OK || echo FAIL'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "do not claim to have read files outside the diff" "'"$PROMPT_FILE"'" && echo OK || echo FAIL'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "FULL ACCESS to the project filesystem" "'"$PROMPT_FILE"'" && echo PRESENT || echo ABSENT'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "evidence from a file you read outside the diff" "'"$PROMPT_FILE"'" && echo PRESENT || echo ABSENT'

uvx showboat note "$DEMO_FILE" \
  "Piece 2a — the deep-verification role framing and the JSON schema block (which the sequencer's parser depends on) are preserved from T-268."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "deep verification review" "'"$PROMPT_FILE"'" && echo OK || echo FAIL'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "\"overall_correctness\"" "'"$PROMPT_FILE"'" && echo OK || echo FAIL'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "\"no_further_concerns\"" "'"$PROMPT_FILE"'" && echo OK || echo FAIL'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "\"review_in_progress\"" "'"$PROMPT_FILE"'" && echo OK || echo FAIL'

# ---------------------------------------------------------------------------
# Piece 3 — JSON schema still round-trips through parse_reviewer_output.
#
# python3 -c, NOT `uv run pytest` — conftest's session-autouse Postgres
# fixture breaks showboat verify on a clean host. A direct import bypasses
# conftest.
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Piece 3 — a minimal payload matching the preserved schema round-trips through parse_reviewer_output. Approve → verdict='approve'; priority-3 finding → verdict='request_changes'."
uvx showboat exec "$DEMO_FILE" bash \
  'uv run python3 -c "
import json
from src.gateway.review_engine import parse_reviewer_output

approve_payload = json.dumps({
    \"findings\": [],
    \"overall_correctness\": \"patch is correct\",
    \"overall_explanation\": \"reviewed cleanly.\",
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

# ---------------------------------------------------------------------------
# Piece 4 — LIVE PROOF. `opencode run --pure` emits the expected literal JSON
# end-to-end in one shot. Output reduced to an OK/FAIL boolean so the live
# call is byte-deterministic under `showboat verify` (no timings, no tokens,
# no model drift in captured output).
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Piece 4 — LIVE: opencode run --pure with the real model answers a literal-JSON prompt with the literal JSON. Output reduced to OK/FAIL so the capture is byte-deterministic under showboat verify."
uvx showboat exec "$DEMO_FILE" bash \
  'out=$(opencode run --pure --model ollama/gemma4-e4b-32k --log-level ERROR --dangerously-skip-permissions -- "Emit the literal JSON {\"test\":\"ok\"} and nothing else." 2>&1 || true); echo "$out" | grep -Eq "\"test\"[[:space:]]*:[[:space:]]*\"ok\"" && echo OK || echo FAIL'

uvx showboat verify "$DEMO_FILE"
