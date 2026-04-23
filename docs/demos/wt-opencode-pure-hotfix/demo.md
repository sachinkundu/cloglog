# HOTFIX: --pure is back in the opencode argv so gemma4-e4b-32k emits JSON instead of narrating tool calls, and the prompt no longer claims filesystem access the model does not have under --pure.

*2026-04-23T10:23:24Z by Showboat 0.6.1*
<!-- showboat-id: e5c8bf27-62e3-460f-8081-e7894a3a484a -->

Piece 1 — src/gateway/review_loop.py now passes --pure AND --dangerously-skip-permissions in the opencode argv. --pure disables the default plugin set that gives the model tool access; without it, gemma4-e4b-32k narrates tool calls instead of emitting JSON (observed on PR #194).

```bash
grep -q -- "\"--pure\"" "src/gateway/review_loop.py" && echo OK || echo FAIL
```

```output
OK
```

```bash
grep -q -- "\"--dangerously-skip-permissions\"" "src/gateway/review_loop.py" && echo OK || echo FAIL
```

```output
OK
```

Piece 2 — .github/opencode/prompts/review.md no longer claims filesystem access the model does not have under --pure. The honest 'no tool access' framing replaces 'FULL ACCESS to the project filesystem' and 'evidence from a file you read outside the diff'.

```bash
grep -q "no tool access" ".github/opencode/prompts/review.md" && echo OK || echo FAIL
```

```output
OK
```

```bash
grep -q "do not claim to have read files outside the diff" ".github/opencode/prompts/review.md" && echo OK || echo FAIL
```

```output
OK
```

```bash
grep -q "FULL ACCESS to the project filesystem" ".github/opencode/prompts/review.md" && echo PRESENT || echo ABSENT
```

```output
ABSENT
```

```bash
grep -q "evidence from a file you read outside the diff" ".github/opencode/prompts/review.md" && echo PRESENT || echo ABSENT
```

```output
ABSENT
```

Piece 2a — the deep-verification role framing and the JSON schema block (which the sequencer's parser depends on) are preserved from T-268.

```bash
grep -q "deep verification review" ".github/opencode/prompts/review.md" && echo OK || echo FAIL
```

```output
OK
```

```bash
grep -q "\"overall_correctness\"" ".github/opencode/prompts/review.md" && echo OK || echo FAIL
```

```output
OK
```

```bash
grep -q "\"no_further_concerns\"" ".github/opencode/prompts/review.md" && echo OK || echo FAIL
```

```output
OK
```

```bash
grep -q "\"review_in_progress\"" ".github/opencode/prompts/review.md" && echo OK || echo FAIL
```

```output
OK
```

Piece 3 — a minimal payload matching the preserved schema round-trips through parse_reviewer_output. Approve → verdict='approve'; priority-3 finding → verdict='request_changes'.

```bash
uv run python3 -c "
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
"
```

```output
2 parse assertions passed
```

Piece 4 — LIVE: opencode run --pure with the real model answers a literal-JSON prompt with the literal JSON. Output reduced to OK/FAIL so the capture is byte-deterministic under showboat verify.

```bash
out=$(opencode run --pure --model ollama/gemma4-e4b-32k --log-level ERROR --dangerously-skip-permissions -- "Emit the literal JSON {\"test\":\"ok\"} and nothing else." 2>&1 || true); echo "$out" | grep -Eq "\"test\"[[:space:]]*:[[:space:]]*\"ok\"" && echo OK || echo FAIL
```

```output
OK
```
