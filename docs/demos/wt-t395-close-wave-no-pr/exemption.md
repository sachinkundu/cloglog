---
verdict: no_demo
diff_hash: 557df6d03f8628e54bf7f25648ac38200dbd40567897f721828309dca8f2834d
classifier: demo-classifier
generated_at: 2026-05-04T14:00:00Z
---

## Why no demo

The `src/agent/services.py` change modifies the guard that blocks agent-driven `done`
transitions, carving out an exception for close-off tasks (`close_off_worktree_id is not
None`, or title prefix `Close worktree ` for legacy stale rows with NULL FK). No HTTP route
decorator was added or changed, no request/response schema changed, and no new API endpoint
was exposed. The behavioural change (close-off tasks can now reach `done` via agent) is an
internal workflow state machine change with no user-visible UI or HTTP surface difference.
Counterfactual: if the diff had added a `@router.patch` decorator or modified the Pydantic
response model for `update_task_status`, the verdict would be `needs_demo`.

## Changed files

- docs/invariants.md
- plugins/cloglog/skills/close-wave/SKILL.md
- plugins/cloglog/skills/reconcile/SKILL.md
- src/agent/services.py
- tests/agent/test_unit.py
- tests/plugins/test_allow_main_commit_override_scope.py
- tests/plugins/test_close_wave_skill_lifecycle_calls.py
- tests/plugins/test_close_wave_skill_no_detached_push.py
