---
verdict: no_demo
diff_hash: c72e0bb9d912dac0fdf1684914f83060cf6ec1f0b4b6671baf25af6bc7c846b8
classifier: demo-classifier
generated_at: 2026-04-26T00:00:00Z
---

## Why no demo

Diff replaces the webhook resolver's main-agent lookup from
`settings.main_agent_inbox_path` to a new `worktrees.role` column
(migration a3f1d2c4b5e7, new `AgentRepository.get_main_agent_worktree`,
role derivation in `services.py`). The strongest needs_demo candidate
was `src/agent/routes.py`, but the change is inside the existing
`create_close_off_task` body — no decorator added/changed,
request/response schema unchanged, and the user-observable contract
(assign to main agent when present, otherwise unassigned) is preserved.
Webhook routing behavior at the HTTP boundary is also unchanged: `PR_*`
events still reach the main inbox, `ISSUE_COMMENT` still excluded.
Counterfactual: if the diff had added a new `@router` decorator,
changed the close-off response shape, or surfaced the new `role` field
in any API/UI/MCP response, the verdict would have been `needs_demo`.

## Changed files

- src/agent/models.py
- src/agent/repository.py
- src/agent/routes.py
- src/agent/services.py
- src/alembic/versions/a3f1d2c4b5e7_add_worktree_role.py
- src/gateway/webhook_consumers.py
- tests/gateway/test_webhook_consumers.py
