# T-270 — reconcile delegates to close-wave for cleanly-completed worktrees so shutdown-artifacts survive archive; Cases A/B/C remain as the dirty-path fallback.

*2026-04-23T10:01:14Z by Showboat 0.6.1*
<!-- showboat-id: b05d5aca-8132-4e50-8122-127be99677aa -->

Proof 1 — reconcile SKILL.md introduces Step 5.0 delegation branch with the verbatim 'delegate to close-wave' phrasing. Grep targets the skill file only so unrelated future docs mentioning the phrase cannot mask a regression.

```bash

f=plugins/cloglog/skills/reconcile/SKILL.md
grep -q "Step 5.0" "$f" && grep -q "delegate the entire teardown to close-wave" "$f" \
  && echo "OK reconcile Step 5.0 delegation present" \
  || { echo "FAIL reconcile Step 5.0 delegation missing"; exit 1; }

```

```output
OK reconcile Step 5.0 delegation present
```

Proof 2a — predicate component 1 (shutdown-artifacts/work-log.md filesystem check) is referenced in reconcile Step 5.0.

```bash

f=plugins/cloglog/skills/reconcile/SKILL.md
grep -q "shutdown-artifacts/work-log.md" "$f" \
  && echo "OK predicate-1 (shutdown-artifacts) referenced" \
  || { echo "FAIL predicate-1 reference missing"; exit 1; }

```

```output
OK predicate-1 (shutdown-artifacts) referenced
```

Proof 2b — predicate component 2 (close-off task in backlog) is referenced in reconcile Step 5.0.

```bash

f=plugins/cloglog/skills/reconcile/SKILL.md
grep -qi "close-off task" "$f" \
  && echo "OK predicate-2 (close-off task) referenced" \
  || { echo "FAIL predicate-2 reference missing"; exit 1; }

```

```output
OK predicate-2 (close-off task) referenced
```

Proof 2c — predicate component 3 (every assigned task has pr_merged=True) is referenced in reconcile Step 5.0.

```bash

f=plugins/cloglog/skills/reconcile/SKILL.md
grep -q "pr_merged=True" "$f" \
  && echo "OK predicate-3 (pr_merged=True) referenced" \
  || { echo "FAIL predicate-3 reference missing"; exit 1; }

```

```output
OK predicate-3 (pr_merged=True) referenced
```

Proof 3 — reconcile SKILL.md still carries Cases A/B/C as the dirty-path fallback for agents that crashed, wedged, or never wrote shutdown-artifacts. The T-270 change is additive, not a rewrite.

```bash

f=plugins/cloglog/skills/reconcile/SKILL.md
grep -q "### Case A — PR merged, agent still registered" "$f" \
  && grep -q "### Case B — Wedged agent" "$f" \
  && grep -q "### Case C — Orphaned worktree" "$f" \
  && echo "OK Cases A/B/C all present" \
  || { echo "FAIL one or more fallback cases missing"; exit 1; }

```

```output
OK Cases A/B/C all present
```

Proof 4 — docs/design/agent-lifecycle.md §5 documents the unified flow paragraph naming reconcile as the arbiter and T-270 as the originating task. This is the authoritative spec that future agents will read.

```bash

f=docs/design/agent-lifecycle.md
grep -q "Reconcile is the arbiter" "$f" \
  && grep -q "T-270" "$f" \
  && echo "OK agent-lifecycle §5 unified-flow paragraph present" \
  || { echo "FAIL unified-flow paragraph missing"; exit 1; }

```

```output
OK agent-lifecycle §5 unified-flow paragraph present
```

Proof 5 — close-wave SKILL.md declares an 'Invocation modes' section with a 'Reconcile delegation' entry point and explicitly states user confirmation (Step 1.5) is skipped when invoked from reconcile.

```bash

f=plugins/cloglog/skills/close-wave/SKILL.md
grep -q "Invocation modes" "$f" \
  && grep -q "Reconcile delegation" "$f" \
  && grep -q "Skip Step 1.5" "$f" \
  && echo "OK close-wave reconcile-callable entry point documented" \
  || { echo "FAIL close-wave Invocation modes / Reconcile delegation / Step 1.5 skip missing"; exit 1; }

```

```output
OK close-wave reconcile-callable entry point documented
```

Proof 6 — pin test tests/plugins/test_reconcile_skill_structure.py has 5 assertions covering the delegation branch, three predicate components, fallback cases, and the unified-flow doc. Import-direct (not pytest) so this block survives showboat verify on a clean host without a live Postgres DB (conftest.py has a session-autouse DB fixture).

```bash

python3 -c "import sys; sys.path.insert(0, \"tests/plugins\"); import test_reconcile_skill_structure as t; t.test_reconcile_skill_has_close_wave_delegation_branch(); t.test_reconcile_skill_references_all_three_predicate_components(); t.test_reconcile_skill_keeps_cases_a_b_c_as_fallbacks(); t.test_close_wave_skill_documents_reconcile_delegation(); t.test_agent_lifecycle_documents_unified_teardown_flow(); print(\"5 assertions passed\")"

```

```output
5 assertions passed
```
