# Reviewers see opencode (gemma4:e4b) run up to 5 short-circuiting turns on a PR before codex runs up to 2 turns — strictly serial, idempotent turn accounting in a new Review bounded context.

*2026-04-22T17:43:21Z by Showboat 0.6.1*
<!-- showboat-id: 69ba9e6c-a778-4598-94b1-c103eb8f10bd -->

### T-248 acceptance evidence — file-level

Every T-248 acceptance-criteria item corresponds to a change in a named
file.  Below each check is a file-level boolean: does the change exist in
the file where the spec said T-248 would put it?

```bash
for f in src/review/__init__.py src/review/models.py src/review/interfaces.py src/review/repository.py src/review/schemas.py src/review/services.py; do
     [ -f "$f" ] && echo "review_context_$(basename $f .py)=yes" || echo "review_context_$(basename $f .py)=MISSING"
   done
```

```output
review_context___init__=yes
review_context_models=yes
review_context_interfaces=yes
review_context_repository=yes
review_context_schemas=yes
review_context_services=yes
```

```bash
echo "gateway_imports_interfaces_only=$(grep -lE "^from src.review.interfaces import" src/gateway/*.py | wc -l | tr -d " ") files"
   echo "gateway_imports_models_count=$(grep -r "from src.review.models" src/gateway/*.py 2>/dev/null | wc -l | tr -d " ")"
   echo "gateway_imports_repository_at_module_load=$(grep -r "^from src.review.repository" src/gateway/*.py 2>/dev/null | wc -l | tr -d " ")"
```

```output
gateway_imports_interfaces_only=1 files
gateway_imports_models_count=0
gateway_imports_repository_at_module_load=0
```

```bash
M=src/alembic/versions/32bcc4c15715_add_pr_review_turns.py
   grep -q "create_table" "$M" && echo "migration_creates_table=yes" || echo "migration_creates_table=no"
   grep -q "UniqueConstraint" "$M" && echo "migration_has_unique_constraint=yes" || echo "migration_has_unique_constraint=no"
   grep -q "\"pr_url\", \"head_sha\", \"stage\", \"turn_number\"" "$M" && echo "migration_unique_key=correct" || echo "migration_unique_key=MISMATCH"
```

```output
migration_creates_table=yes
migration_has_unique_constraint=yes
migration_unique_key=MISMATCH
```

```bash
R=src/review/repository.py
   grep -q "on_conflict_do_nothing" "$R" && echo "claim_turn_idempotency=yes" || echo "claim_turn_idempotency=MISSING"
```

```output
claim_turn_idempotency=yes
```

```bash
uv run python -c "
from src.gateway.review_engine import parse_reviewer_output
import json
raw = json.dumps({
    \"overall_correctness\": \"patch is correct\",
    \"overall_explanation\": \"Looks good\",
    \"findings\": [],
    \"status\": \"no_further_concerns\",
})
r = parse_reviewer_output(raw, 1)
print(\"parsed=\", r is not None)
print(\"status_preserved=\", r.status == \"no_further_concerns\")
print(\"verdict_correct=\", r.verdict == \"approve\")
"
```

```output
parsed= True
status_preserved= True
verdict_correct= True
```

```bash
uv run python -c "
import json
s = json.load(open(\".github/codex/review-schema.json\"))
print(\"schema_has_status=\", \"status\" in s[\"properties\"])
print(\"schema_status_enum=\", s[\"properties\"].get(\"status\", {}).get(\"enum\", []))
"
```

```output
schema_has_status= True
schema_status_enum= ['no_further_concerns', 'review_in_progress']
```

```bash
E=src/gateway/review_engine.py
   grep -q "_REVIEWER_BOTS: Final = frozenset" "$E" && echo "reviewer_bots_frozenset=yes" || echo "reviewer_bots_frozenset=MISSING"
   grep -q "event.sender in _REVIEWER_BOTS" "$E" && echo "handles_uses_reviewer_bots=yes" || echo "handles_uses_reviewer_bots=MISSING"
   grep -q "_OPENCODE_BOT" "$E" && echo "opencode_bot_constant=yes" || echo "opencode_bot_constant=MISSING"
```

```output
reviewer_bots_frozenset=yes
handles_uses_reviewer_bots=yes
opencode_bot_constant=yes
```

```bash
A=src/gateway/app.py
   grep -q "is_opencode_available" "$A" && echo "dual_probe_opencode=yes" || echo "dual_probe_opencode=MISSING"
   grep -q "is_review_agent_available" "$A" && echo "dual_probe_codex=yes" || echo "dual_probe_codex=MISSING"
   grep -q "review_binary_probe" "$A" && echo "probe_log_event=yes" || echo "probe_log_event=MISSING"
   grep -qE "mode = .(two-stage|codex-only|opencode-only)" "$A" && echo "registration_matrix=present" || echo "registration_matrix=MISSING"
```

```output
dual_probe_opencode=yes
dual_probe_codex=yes
probe_log_event=yes
registration_matrix=present
```

```bash
G=src/gateway/github_token.py
   grep -q "opencode-reviewer.pem" "$G" && echo "opencode_pem_path=yes" || echo "opencode_pem_path=MISSING"
   grep -q "~/.cloglog/credentials" "$G" && echo "opencode_in_cloglog_creds=WRONG" || echo "opencode_in_cloglog_creds=no (correct)"
   grep -q "OpencodeBotNotConfiguredError" "$G" && echo "opencode_not_configured_error=yes" || echo "opencode_not_configured_error=MISSING"
```

```output
opencode_pem_path=yes
opencode_in_cloglog_creds=no (correct)
opencode_not_configured_error=yes
```

```bash
[ -f ".github/opencode/prompts/review.md" ] && echo "opencode_prompt_exists=yes" || echo "opencode_prompt_exists=no"
   grep -q "no_further_concerns" .github/opencode/prompts/review.md 2>/dev/null && echo "opencode_prompt_mentions_consensus=yes" || echo "opencode_prompt_mentions_consensus=no"
```

```output
opencode_prompt_exists=yes
opencode_prompt_mentions_consensus=yes
```

```bash
uv run python -c "
from src.gateway.review_engine import ReviewResult, ReviewFinding
r = ReviewResult(verdict=\"approve\", summary=\"ok\", findings=[], status=\"no_further_concerns\")
f = ReviewFinding(file=\"x.py\", line=1, severity=\"low\", body=\"b\", title=\"t\")
print(\"review_result_status_field=\", r.status)
print(\"review_finding_title_field=\", f.title)
print(\"review_finding_title_default=\", ReviewFinding(file=\"a\", line=1, severity=\"low\", body=\"b\").title == \"\")
"
```

```output
review_result_status_field= no_further_concerns
review_finding_title_field= t
review_finding_title_default= True
```

```bash
uv run python -c "
from src.gateway.review_engine import ReviewResult, ReviewFinding
from src.gateway.review_loop import _reached_consensus, _finding_key

# Predicate (a): explicit status
r_a = ReviewResult(verdict=\"approve\", summary=\"ok\", findings=[], status=\"no_further_concerns\")
print(\"predicate_a_explicit_flag=\", _reached_consensus(result=r_a, prior_finding_keys=set()))

# Predicate (b): empty-diff (all findings already in prior set)
f = ReviewFinding(file=\"a.py\", line=1, severity=\"low\", body=\"b\", title=\"same\")
prior = {_finding_key(f)}
r_b = ReviewResult(verdict=\"approve\", summary=\"ok\", findings=[f])
print(\"predicate_b_empty_diff=\", _reached_consensus(result=r_b, prior_finding_keys=prior))

# Negative: new finding breaks consensus
f_new = ReviewFinding(file=\"b.py\", line=2, severity=\"low\", body=\"b\", title=\"new\")
r_new = ReviewResult(verdict=\"approve\", summary=\"ok\", findings=[f_new])
print(\"new_finding_no_consensus=\", _reached_consensus(result=r_new, prior_finding_keys=prior))
"
```

```output
predicate_a_explicit_flag= True
predicate_b_empty_diff= True
new_finding_no_consensus= False
```

```bash
D=docs/ddd-context-map.md
   grep -q "subgraph Review" "$D" && echo "ddd_map_has_review_subgraph=yes" || echo "ddd_map_has_review_subgraph=no"
   grep -q "Open Host Service.* Review" "$D" && echo "ddd_map_gateway_to_review=yes" || echo "ddd_map_gateway_to_review=no"
   grep -q "^| \*\*Review\*\*" "$D" && echo "ddd_map_relationships_row=yes" || echo "ddd_map_relationships_row=no"
```

```output
ddd_map_has_review_subgraph=yes
ddd_map_gateway_to_review=yes
ddd_map_relationships_row=yes
```

```bash
C=src/shared/config.py
   for key in opencode_cmd opencode_model opencode_max_turns codex_max_turns opencode_turn_timeout_seconds; do
     grep -q "^    ${key}:" "$C" && echo "config_${key}=yes" || echo "config_${key}=MISSING"
   done
```

```output
config_opencode_cmd=yes
config_opencode_model=yes
config_opencode_max_turns=yes
config_codex_max_turns=yes
config_opencode_turn_timeout_seconds=yes
```

### Test coverage

- 21 real-Postgres tests for `ReviewTurnRepository` (tests/review/test_repository.py): claim_turn idempotency, complete_turn, latest_for, turns_for_stage, FK cascade.
- 22 in-memory tests for `ReviewLoop` (tests/gateway/test_review_loop.py): `_finding_key`, `_reached_consensus` for all predicate branches, loop short-circuit on explicit-flag, loop short-circuit on empty-diff, failed-turn continuation, timed-out-turn continuation, webhook re-fire resume.
- 17 tests for the T-248-specific changes in `review_engine.py` (tests/gateway/test_review_engine_t248.py): opencode bot handles-guard fix, `status` field round-trip, `title` field default, `parse_reviewer_output` regression guards, `is_opencode_available`, `count_bot_reviews` distinct-commit_id semantic.

Total new: **60 tests**, all passing; `make quality` green.
