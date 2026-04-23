# Fix codex reviewer wiring — review-schema.json is now valid under OpenAI Structured Outputs (required + nullable status) and the consensus predicate short-circuits on a turn-1 approve verdict, so opencode hands off immediately when it has nothing to flag.

*2026-04-23T06:24:05Z by Showboat 0.6.1*
<!-- showboat-id: 0c25ae99-f6c0-4a10-9f9d-f15bd2b23ff0 -->

Before: .github/codex/review-schema.json listed status in properties but not in required. OpenAI's Structured Outputs API rejected the schema with 400 invalid_json_schema on every codex exec call, so the codex reviewer posted zero reviews on every PR between 2026-04-23T05:32Z (PR #187 merge) and this fix. Each codex turn failed in ~2.5-3s, consistent with an OpenAI 400 round-trip.

Before: even when a reviewer's verdict was approve on turn 1 (no findings or patch is correct), ReviewLoop.run did not short-circuit unless an explicit status=no_further_concerns flag was present OR the finding-keys set was empty. Turn-1 approves with nit-level findings ran additional turns unnecessarily, contrary to user intent: if it says pass, it should just do one.

Fix: add status to required in review-schema.json with type [string, null] and null in the enum (OpenAI rule). Add predicate verdict == approve to _reached_consensus so a pass verdict itself short-circuits. Sharpen opencode prompt so turn-1 pure passes emit status=no_further_concerns directly. Add a regression test pinning the OpenAI-compatibility shape of the schema.

Proof 1 — every object schema in review-schema.json lists every one of its properties in required (OpenAI Structured Outputs rule). The top-level status field is both required AND nullable via type [string, null].

```bash

python3 - <<PY
import json, pathlib
schema = json.loads(pathlib.Path(".github/codex/review-schema.json").read_text())

def objs(node):
    if isinstance(node, dict):
        t = node.get("type")
        if t == "object" or (isinstance(t, list) and "object" in t):
            yield node
        for v in node.values():
            yield from objs(v)
    elif isinstance(node, list):
        for x in node:
            yield from objs(x)

violations = []
for sub in objs(schema):
    props = sub.get("properties") or {}
    if not props:
        continue
    missing = set(props.keys()) - set(sub.get("required", []))
    if missing:
        violations.append("missing from required: " + repr(sorted(missing)))
    if sub.get("additionalProperties") is not False:
        violations.append("additionalProperties must be false")
assert not violations, violations

assert "status" in schema["required"], "status must be in top-level required"
st = schema["properties"]["status"]
t = st["type"]
assert isinstance(t, list) and "null" in t, "status.type must be a list containing null"
assert None in st["enum"], "status.enum must include null"
print("OK schema passes OpenAI Structured Outputs rules")
PY

```

```output
OK schema passes OpenAI Structured Outputs rules
```

Proof 2 — _reached_consensus in src/gateway/review_loop.py now contains a verdict == approve predicate in addition to the explicit status flag and the empty finding-diff check. AST walk confirms the three predicates are present.

```bash

python3 - <<PY
import ast, pathlib, textwrap
src = pathlib.Path("src/gateway/review_loop.py").read_text()
tree = ast.parse(src)
fn = next(
    node for node in ast.walk(tree)
    if isinstance(node, ast.FunctionDef) and node.name == "_reached_consensus"
)
body = ast.unparse(fn)
assert "result.status == " in body and "no_further_concerns" in body, "predicate a (explicit status) missing"
assert "result.verdict == " in body and "approve" in body, "predicate b (approve verdict) missing"
assert "prior_finding_keys" in body and "_finding_key" in body, "predicate c (empty diff) missing"
print("OK _reached_consensus holds 3 short-circuit predicates: status, approve verdict, empty diff")
PY

```

```output
OK _reached_consensus holds 3 short-circuit predicates: status, approve verdict, empty diff
```

Proof 3 — parse_reviewer_output in src/gateway/review_engine.py reads the status field from the codex schema payload and copies it through to ReviewResult. Source inspection confirms the normalization preserves status.

```bash

python3 - <<PY
import ast, pathlib
src = pathlib.Path("src/gateway/review_engine.py").read_text()
tree = ast.parse(src)
fn = next(
    node for node in ast.walk(tree)
    if isinstance(node, ast.FunctionDef) and node.name == "parse_reviewer_output"
)
body = ast.unparse(fn)
assert "data.get(" in body and "status" in body, "parser must read the status field from the payload"
# ast.unparse normalizes quotes; pick whichever form is emitted.
lower = body.replace(chr(39), chr(34))
assert (chr(34) + "status" + chr(34) + ": status") in lower, "parser must copy status into the rewritten dict"
print("OK parse_reviewer_output reads and preserves the status field across the codex-schema normalization")
PY

```

```output
OK parse_reviewer_output reads and preserves the status field across the codex-schema normalization
```
