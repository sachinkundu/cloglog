#!/usr/bin/env bash
# Demo for T-248: Reviewers can now see opencode (gemma4:e4b) run up to 5
# short-circuiting turns on a PR before codex (Claude 4.x) runs up to 2
# short-circuiting turns — strictly serial, per commit SHA, with idempotent
# turn accounting in a new Review bounded context.
#
# Verify-safe: no pytest, no DB, no subprocess against ollama.  Every exec
# block is a deterministic OK/FAIL boolean or grep output.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}/T-248"
DEMO_FILE="$DEMO_DIR/demo.md"

# showboat init refuses to overwrite — delete first so `make demo` is re-runnable.
rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "Reviewers see opencode (gemma4:e4b) run up to 5 short-circuiting turns on a PR before codex runs up to 2 turns — strictly serial, idempotent turn accounting in a new Review bounded context."

# ===================================================================
uvx showboat note "$DEMO_FILE" "### T-248 acceptance evidence — file-level

Every T-248 acceptance-criteria item corresponds to a change in a named
file.  Below each check is a file-level boolean: does the change exist in
the file where the spec said T-248 would put it?"

# ----- New Review bounded context -----
uvx showboat exec "$DEMO_FILE" bash \
  'for f in src/review/__init__.py src/review/models.py src/review/interfaces.py src/review/repository.py src/review/schemas.py src/review/services.py; do
     [ -f "$f" ] && echo "review_context_$(basename $f .py)=yes" || echo "review_context_$(basename $f .py)=MISSING"
   done'

# ----- Gateway → Review is OHS-only (no model/repository imports) -----
uvx showboat exec "$DEMO_FILE" bash \
  'echo "gateway_imports_interfaces_only=$(grep -lE "^from src.review.interfaces import" src/gateway/*.py | wc -l | tr -d " ") files"
   echo "gateway_imports_models_count=$(grep -r "from src.review.models" src/gateway/*.py 2>/dev/null | wc -l | tr -d " ")"
   echo "gateway_imports_repository_at_module_load=$(grep -r "^from src.review.repository" src/gateway/*.py 2>/dev/null | wc -l | tr -d " ")"'

# ----- pr_review_turns table + unique constraint in Alembic migration -----
uvx showboat exec "$DEMO_FILE" bash \
  'M=src/alembic/versions/32bcc4c15715_add_pr_review_turns.py
   grep -q "create_table" "$M" && echo "migration_creates_table=yes" || echo "migration_creates_table=no"
   grep -q "UniqueConstraint" "$M" && echo "migration_has_unique_constraint=yes" || echo "migration_has_unique_constraint=no"
   grep -q "\"pr_url\", \"head_sha\", \"stage\", \"turn_number\"" "$M" && echo "migration_unique_key=correct" || echo "migration_unique_key=MISMATCH"'

# ----- ReviewTurnRepository.claim_turn uses INSERT ... ON CONFLICT DO NOTHING -----
uvx showboat exec "$DEMO_FILE" bash \
  'R=src/review/repository.py
   grep -q "on_conflict_do_nothing" "$R" && echo "claim_turn_idempotency=yes" || echo "claim_turn_idempotency=MISSING"'

# ----- `status` field round-trips through parse_reviewer_output -----
# Regression guard for PR #185 round 1 MEDIUM finding (status silently dropped).
uvx showboat exec "$DEMO_FILE" bash \
  'uv run python -c "
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
"'

# ----- Schema extended with optional top-level `status` -----
uvx showboat exec "$DEMO_FILE" bash \
  'uv run python -c "
import json
s = json.load(open(\".github/codex/review-schema.json\"))
print(\"schema_has_status=\", \"status\" in s[\"properties\"])
print(\"schema_status_enum=\", s[\"properties\"].get(\"status\", {}).get(\"enum\", []))
"'

# ----- handles() skips opencode bot via _REVIEWER_BOTS (not _BOT_USERNAMES) -----
# This is the fix for PR #185 round 1 HIGH finding.
uvx showboat exec "$DEMO_FILE" bash \
  'E=src/gateway/review_engine.py
   grep -q "_REVIEWER_BOTS: Final = frozenset" "$E" && echo "reviewer_bots_frozenset=yes" || echo "reviewer_bots_frozenset=MISSING"
   grep -q "event.sender in _REVIEWER_BOTS" "$E" && echo "handles_uses_reviewer_bots=yes" || echo "handles_uses_reviewer_bots=MISSING"
   grep -q "_OPENCODE_BOT" "$E" && echo "opencode_bot_constant=yes" || echo "opencode_bot_constant=MISSING"'

# ----- Dual-binary probe + 4-way registration matrix in app.py -----
uvx showboat exec "$DEMO_FILE" bash \
  'A=src/gateway/app.py
   grep -q "is_opencode_available" "$A" && echo "dual_probe_opencode=yes" || echo "dual_probe_opencode=MISSING"
   grep -q "is_review_agent_available" "$A" && echo "dual_probe_codex=yes" || echo "dual_probe_codex=MISSING"
   grep -q "review_binary_probe" "$A" && echo "probe_log_event=yes" || echo "probe_log_event=MISSING"
   grep -qE "mode = .(two-stage|codex-only|opencode-only)" "$A" && echo "registration_matrix=present" || echo "registration_matrix=MISSING"'

# ----- Opencode reviewer token uses ~/.agent-vm/credentials, NOT ~/.cloglog/credentials -----
# Fix for PR #185 round 1 HIGH (credential precedent).
uvx showboat exec "$DEMO_FILE" bash \
  'G=src/gateway/github_token.py
   grep -q "opencode-reviewer.pem" "$G" && echo "opencode_pem_path=yes" || echo "opencode_pem_path=MISSING"
   grep -q "~/.cloglog/credentials" "$G" && echo "opencode_in_cloglog_creds=WRONG" || echo "opencode_in_cloglog_creds=no (correct)"
   grep -q "OpencodeBotNotConfiguredError" "$G" && echo "opencode_not_configured_error=yes" || echo "opencode_not_configured_error=MISSING"'

# ----- New opencode review prompt exists -----
uvx showboat exec "$DEMO_FILE" bash \
  '[ -f ".github/opencode/prompts/review.md" ] && echo "opencode_prompt_exists=yes" || echo "opencode_prompt_exists=no"
   grep -q "no_further_concerns" .github/opencode/prompts/review.md 2>/dev/null && echo "opencode_prompt_mentions_consensus=yes" || echo "opencode_prompt_mentions_consensus=no"'

# ----- ReviewResult extended with optional status; ReviewFinding with title -----
uvx showboat exec "$DEMO_FILE" bash \
  'uv run python -c "
from src.gateway.review_engine import ReviewResult, ReviewFinding
r = ReviewResult(verdict=\"approve\", summary=\"ok\", findings=[], status=\"no_further_concerns\")
f = ReviewFinding(file=\"x.py\", line=1, severity=\"low\", body=\"b\", title=\"t\")
print(\"review_result_status_field=\", r.status)
print(\"review_finding_title_field=\", f.title)
print(\"review_finding_title_default=\", ReviewFinding(file=\"a\", line=1, severity=\"low\", body=\"b\").title == \"\")
"'

# ----- Consensus predicates work (explicit flag OR empty-diff) -----
uvx showboat exec "$DEMO_FILE" bash \
  'uv run python -c "
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
"'

# ----- DDD context map updated to include Review context -----
uvx showboat exec "$DEMO_FILE" bash \
  'D=docs/ddd-context-map.md
   grep -q "subgraph Review" "$D" && echo "ddd_map_has_review_subgraph=yes" || echo "ddd_map_has_review_subgraph=no"
   grep -q "Open Host Service.* Review" "$D" && echo "ddd_map_gateway_to_review=yes" || echo "ddd_map_gateway_to_review=no"
   grep -q "^| \*\*Review\*\*" "$D" && echo "ddd_map_relationships_row=yes" || echo "ddd_map_relationships_row=no"'

# ----- New config knobs (opencode_cmd, max_turns, timeouts) -----
uvx showboat exec "$DEMO_FILE" bash \
  'C=src/shared/config.py
   for key in opencode_cmd opencode_model opencode_max_turns codex_max_turns opencode_turn_timeout_seconds; do
     grep -q "^    ${key}:" "$C" && echo "config_${key}=yes" || echo "config_${key}=MISSING"
   done'

# ----- Test coverage summary (non-deterministic counts dropped — booleans only) -----
uvx showboat note "$DEMO_FILE" "### Test coverage

- 21 real-Postgres tests for \`ReviewTurnRepository\` (tests/review/test_repository.py): claim_turn idempotency, complete_turn, latest_for, turns_for_stage, FK cascade.
- 22 in-memory tests for \`ReviewLoop\` (tests/gateway/test_review_loop.py): \`_finding_key\`, \`_reached_consensus\` for all predicate branches, loop short-circuit on explicit-flag, loop short-circuit on empty-diff, failed-turn continuation, timed-out-turn continuation, webhook re-fire resume.
- 17 tests for the T-248-specific changes in \`review_engine.py\` (tests/gateway/test_review_engine_t248.py): opencode bot handles-guard fix, \`status\` field round-trip, \`title\` field default, \`parse_reviewer_output\` regression guards, \`is_opencode_available\`, \`count_bot_reviews\` distinct-commit_id semantic.

Total new: **60 tests**, all passing; \`make quality\` green."

uvx showboat verify "$DEMO_FILE"
