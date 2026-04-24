---
verdict: no_demo
diff_hash: b52a65299c8eca9f48d8ee71f4ab53a9dc23691f3ea3c60fecdf160c4419cead
classifier: demo-classifier
generated_at: 2026-04-24T14:15:00Z
---

## Why no demo

Signal / counter-signal: the diff touches only `.claude/agents/demo-classifier.md` (pure workflow documentation — two-dot to three-dot correction plus explanatory prose) and `src/shared/events.py` where the sole change is a one-line docstring added to `EventBus.subscribe`. No `@router.*` decorator changes, no `server.tool(...)` edits, no `frontend/src/**` output change, no CLI stdout surface, no migration. The strongest candidate considered was the `src/shared/events.py` edit, but a docstring addition alters neither the function signature, return type, nor runtime behaviour — the SSE / event-bus wire surface is unchanged.

Counterfactual: had `events.py` gained a new public method, altered `subscribe`'s return type, or had the agent markdown been accompanied by a real route/handler change wired into `src/gateway/`, the verdict would flip to `needs_demo`.

## Changed files

- .claude/agents/demo-classifier.md
- src/shared/events.py
