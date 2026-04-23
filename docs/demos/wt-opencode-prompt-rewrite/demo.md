# Opencode reviewer now reads the codebase during review — deep-verification framing replaces first-pass framing and --pure is gone, so verdicts reflect real checks instead of defaulting to pass.

*2026-04-23T08:49:55Z by Showboat 0.6.1*
<!-- showboat-id: 5ebe4be5-499a-4e06-b728-5a73682f2f94 -->

Piece 1 — .github/opencode/prompts/review.md carries the deep-verification framing.

```bash
grep -q "deep verification review" ".github/opencode/prompts/review.md" && echo OK || echo FAIL
```

```output
OK
```

```bash
grep -q "FULL ACCESS to the project filesystem" ".github/opencode/prompts/review.md" && echo OK || echo FAIL
```

```output
OK
```

```bash
grep -q "evidence from a file you read outside the diff" ".github/opencode/prompts/review.md" && echo OK || echo FAIL
```

```output
OK
```

The old pass-biasing framing is gone from the same file.

```bash
grep -iq "first-pass" ".github/opencode/prompts/review.md" && echo PRESENT || echo ABSENT
```

```output
ABSENT
```

```bash
grep -iq "cheap checks" ".github/opencode/prompts/review.md" && echo PRESENT || echo ABSENT
```

```output
ABSENT
```

```bash
grep -iq "leave deep architectural judgement for the cloud reviewer" ".github/opencode/prompts/review.md" && echo PRESENT || echo ABSENT
```

```output
ABSENT
```

```bash
grep -iq "on turn 1 specifically" ".github/opencode/prompts/review.md" && echo PRESENT || echo ABSENT
```

```output
ABSENT
```

The JSON schema block is preserved verbatim — the sequencer's parser depends on this shape.

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

Piece 2 — src/gateway/review_loop.py no longer passes --pure to the opencode CLI, but still passes --dangerously-skip-permissions so opencode does not prompt.

```bash
grep -q -- "\"--pure\"" "src/gateway/review_loop.py" && echo PRESENT || echo ABSENT
```

```output
ABSENT
```

```bash
grep -q -- "\"--dangerously-skip-permissions\"" "src/gateway/review_loop.py" && echo OK || echo FAIL
```

```output
OK
```

Parse-through — an example JSON payload matching the new prompt's schema round-trips through parse_reviewer_output and yields the expected verdict.

```bash
uv run python3 -c "
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
"
```

```output
2 parse assertions passed
```
