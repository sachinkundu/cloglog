#!/usr/bin/env bash
# Demo: T-270 — reconcile Step 5 now delegates to close-wave for cleanly-
# completed worktrees, so shutdown-artifacts survive long enough to be
# archived into docs/work-logs/ instead of being vaporised by
# git worktree remove --force. Cases A/B/C remain the dirty-path fallback.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

DEMO_DIR="${SCRIPT_DIR#"$REPO_ROOT"/}"
DEMO_FILE="$DEMO_DIR/demo.md"

rm -f "$DEMO_FILE"

uvx showboat init "$DEMO_FILE" \
  "T-270 — reconcile delegates to close-wave for cleanly-completed worktrees so shutdown-artifacts survive archive; Cases A/B/C remain as the dirty-path fallback."

uvx showboat note "$DEMO_FILE" \
  "Proof 1 — reconcile SKILL.md introduces Step 5.0 delegation branch with the verbatim 'delegate to close-wave' phrasing. Grep targets the skill file only so unrelated future docs mentioning the phrase cannot mask a regression."

uvx showboat exec "$DEMO_FILE" bash '
f=plugins/cloglog/skills/reconcile/SKILL.md
grep -q "Step 5.0" "$f" && grep -q "delegate the entire teardown to close-wave" "$f" \
  && echo "OK reconcile Step 5.0 delegation present" \
  || { echo "FAIL reconcile Step 5.0 delegation missing"; exit 1; }
'

uvx showboat note "$DEMO_FILE" \
  "Proof 2a — predicate component 1 (shutdown-artifacts/work-log.md filesystem check) is referenced in reconcile Step 5.0."

uvx showboat exec "$DEMO_FILE" bash '
f=plugins/cloglog/skills/reconcile/SKILL.md
grep -q "shutdown-artifacts/work-log.md" "$f" \
  && echo "OK predicate-1 (shutdown-artifacts) referenced" \
  || { echo "FAIL predicate-1 reference missing"; exit 1; }
'

uvx showboat note "$DEMO_FILE" \
  "Proof 2b — predicate component 2 (close-off task in backlog) is referenced in reconcile Step 5.0 AND pins the title-equality match pattern (not worktree_id match). Codex round 1 on this PR caught an earlier version that filtered by worktree_id; close-off tasks carry the main agent worktree_id not the target, so the wrong filter never matched."

uvx showboat exec "$DEMO_FILE" bash '
f=plugins/cloglog/skills/reconcile/SKILL.md
grep -qi "close-off task" "$f" \
  && grep -qF "title == f\"Close worktree {wt_name}\"" "$f" \
  && echo "OK predicate-2 (close-off task by title equality) referenced" \
  || { echo "FAIL predicate-2 title-match pattern missing or uses wrong filter"; exit 1; }
'

uvx showboat note "$DEMO_FILE" \
  "Proof 2c — predicate component 3 accepts all three project-completion terminal states per agent-lifecycle §1 and close_worktree_template (done, OR review+pr_merged=True, OR review+pr_url=None for skip_pr no-PR tasks). Codex round 2 on this PR caught a stricter earlier version that required pr_merged=True everywhere and would have falsely rejected cleanly-completed worktrees whose last task shipped via skip_pr=True."

uvx showboat exec "$DEMO_FILE" bash '
python3 - plugins/cloglog/skills/reconcile/SKILL.md <<'"'"'PY'"'"'
import pathlib, sys
body = pathlib.Path(sys.argv[1]).read_text()
expected = [
    "`status == \"done\"`",
    "`status == \"review\"` AND `pr_merged == True`",
    "`status == \"review\"` AND `pr_url is None`",
]
missing = [e for e in expected if e not in body]
if missing:
    print("FAIL predicate-3 missing:", missing)
    sys.exit(1)
print("OK predicate-3 accepts all three terminal states")
PY
'

uvx showboat note "$DEMO_FILE" \
  "Proof 3 — reconcile SKILL.md still carries Cases A/B/C as the dirty-path fallback for agents that crashed, wedged, or never wrote shutdown-artifacts. The T-270 change is additive, not a rewrite."

uvx showboat exec "$DEMO_FILE" bash '
f=plugins/cloglog/skills/reconcile/SKILL.md
grep -q "### Case A — PR merged, agent still registered" "$f" \
  && grep -q "### Case B — Wedged agent" "$f" \
  && grep -q "### Case C — Orphaned worktree" "$f" \
  && echo "OK Cases A/B/C all present" \
  || { echo "FAIL one or more fallback cases missing"; exit 1; }
'

uvx showboat note "$DEMO_FILE" \
  "Proof 4 — docs/design/agent-lifecycle.md §5 documents the unified flow paragraph naming reconcile as the arbiter and T-270 as the originating task. This is the authoritative spec that future agents will read."

uvx showboat exec "$DEMO_FILE" bash '
f=docs/design/agent-lifecycle.md
grep -q "Reconcile is the arbiter" "$f" \
  && grep -q "T-270" "$f" \
  && echo "OK agent-lifecycle §5 unified-flow paragraph present" \
  || { echo "FAIL unified-flow paragraph missing"; exit 1; }
'

uvx showboat note "$DEMO_FILE" \
  "Proof 5 — close-wave SKILL.md declares an 'Invocation modes' section with a 'Reconcile delegation' entry point and explicitly states user confirmation (Step 1.5) is skipped when invoked from reconcile."

uvx showboat exec "$DEMO_FILE" bash '
f=plugins/cloglog/skills/close-wave/SKILL.md
grep -q "Invocation modes" "$f" \
  && grep -q "Reconcile delegation" "$f" \
  && grep -q "Skip Step 1.5" "$f" \
  && grep -qF "reconcile-<wt-name>" "$f" \
  && echo "OK close-wave reconcile-callable entry point documented with correct <wave-name> shape" \
  || { echo "FAIL close-wave Invocation modes / Reconcile delegation / Step 1.5 skip / <wave-name> shape missing"; exit 1; }
'

uvx showboat note "$DEMO_FILE" \
  "Proof 6 — pin test tests/plugins/test_reconcile_skill_structure.py has 7 assertions covering the delegation branch, three predicate components, fallback cases, the unified-flow doc, and the two round-3 backstops (no doc retains stricter pr_merged-only wording; no doc retains full-filename override shape). Import-direct (not pytest) so this block survives showboat verify on a clean host without a live Postgres DB (conftest.py has a session-autouse DB fixture)."

uvx showboat exec "$DEMO_FILE" bash '
python3 -c "import sys; sys.path.insert(0, \"tests/plugins\"); import test_reconcile_skill_structure as t; t.test_reconcile_skill_has_close_wave_delegation_branch(); t.test_reconcile_skill_references_all_three_predicate_components(); t.test_reconcile_skill_keeps_cases_a_b_c_as_fallbacks(); t.test_close_wave_skill_documents_reconcile_delegation(); t.test_agent_lifecycle_documents_unified_teardown_flow(); t.test_no_doc_retains_the_stricter_pr_merged_only_predicate(); t.test_no_doc_retains_full_filename_wave_name_override(); print(\"7 assertions passed\")"
'

uvx showboat note "$DEMO_FILE" \
  "Proof 7 — no doc across reconcile/close-wave/agent-lifecycle retains the stricter 'every assigned task has pr_merged=True' wording. Codex round 3 MEDIUM caught that fixing the predicate inline left three stale summaries in reconcile Delegation, close-wave Invocation modes, and agent-lifecycle §5.5. All three would have collapsed the three-terminal-state contract back to the wrong stricter form."

uvx showboat exec "$DEMO_FILE" bash '
miss=0
for f in plugins/cloglog/skills/reconcile/SKILL.md plugins/cloglog/skills/close-wave/SKILL.md docs/design/agent-lifecycle.md; do
  if grep -qF "every assigned task has \`pr_merged=True\`." "$f"; then
    echo "FAIL $f retains stricter pr_merged=True wording"
    miss=1
  fi
done
if [ "$miss" -eq 0 ]; then echo "OK no doc retains the stricter pr_merged-only predicate"; else exit 1; fi
'

uvx showboat note "$DEMO_FILE" \
  "Proof 8 — no doc across reconcile/close-wave retains the full-filename shape reconcile-<date>-<wt-name>.md. Codex round 3 HIGH caught that the reconcile Delegation summary still said 'overrides work-log naming to reconcile-<date>-<wt-name>.md' even after close-wave was fixed — the two docs disagreed. Now both use the <wave-name>-substitution shape reconcile-<wt-name>."

uvx showboat exec "$DEMO_FILE" bash '
miss=0
for f in plugins/cloglog/skills/reconcile/SKILL.md plugins/cloglog/skills/close-wave/SKILL.md; do
  if grep -qF "reconcile-<date>-<wt-name>.md" "$f"; then
    echo "FAIL $f retains full-filename shape"
    miss=1
  fi
done
if [ "$miss" -eq 0 ]; then echo "OK no doc retains the full-filename wave-name override"; else exit 1; fi
'

uvx showboat verify "$DEMO_FILE"
