# T-225 — Dogfood `add_task_dependency` on F-48

**Task:** Encode F-48 "Agent Lifecycle Hardening" internal task ordering using the brand-new task-level `blockedBy` MCP tool (T-224).

**Motivation:** T-224 shipped `mcp__cloglog__add_task_dependency`. F-48's ordering was prose in task descriptions — agents had no machine-readable way to avoid starting a task before its prerequisites. This task converts that prose into `task_dependencies` rows so `start_task` now enforces the same ordering.

No application code changes. This PR exists only as an audit trail for the MCP calls that mutated the board.

## F-48 task map (discovered from `get_board`)

| T-# | UUID | Title |
|---|---|---|
| T-213 | `408fb6b3-eef9-461b-bd7f-46a8dc6da8cb` | Broaden "Stop on MCP failure" rule to cover runtime tool errors |
| T-214 | `57d28184-4f45-4687-a70d-199fa6585e0b` | Stop exposing CLOGLOG_API_KEY to agent worktrees |
| T-215 | `eec95394-1420-4127-b529-7c455b48d647` | Unify shutdown inbox path — backend `request_shutdown` writes to `<worktree_path>/.cloglog/inbox` |
| T-216 | `3f61a324-85ea-4a10-af7c-4b71262859a9` | Sync plugin docs/skills to the unified inbox path |
| T-217 | `2dfec97f-8ae3-488b-afc7-0efa1984cc0d` | Fix SessionEnd shutdown hook so it fires when zellij closes the tab |
| T-218 | `a624b7a0-4fb0-491d-ad20-5af8b405baa9` | Add `request_shutdown` MCP tool — expose existing backend endpoint to agents |
| T-219 | `7eb84a0b-bbb6-47c1-9ce5-cecd6bb7f8cc` | Harden `prefer-mcp.sh` — close 127.0.0.1 and keyword-allowlist bypasses |
| T-220 | `29a1612d-5838-43bc-9464-2632ca41c48d` | Rewrite `reconcile` + `close-wave` skills to use cooperative shutdown flow |
| T-221 | `25630871-0717-49d3-af94-3f8f74aabc33` | Admin force-unregister — backend endpoint + MCP tool for wedged agents |
| T-222 | `1875a1ff-ac3f-4501-b80b-74882c56f916` | Canonical agent lifecycle protocol doc — single source of truth |

## Graph encoded

```
T-222 (canonical lifecycle doc, spec)
  ├── T-213   (prefer-mcp.sh broaden)
  ├── T-214   (stop exposing API key)
  ├── T-215   (unify inbox path backend)
  │     ├── T-216  (sync docs to unified path)
  │     └── T-218  (request_shutdown MCP tool)
  │            └── T-220  (rewrite reconcile + close-wave)
  ├── T-217   (fix SessionEnd shutdown hook)
  └── T-219   (harden prefer-mcp.sh)

T-221 (admin force-unregister, independent)
  └── T-220  (rewrite reconcile + close-wave)  [also depends on T-218]
```

9 `blockedBy` edges total.

## MCP calls executed

All nine `mcp__cloglog__add_task_dependency` calls returned 200 with body `"Task dependency added: <task_id> blocked_by <depends_on_id>."`:

| # | task_id | depends_on_id | Meaning |
|---|---|---|---|
| 1 | T-213 (`408fb6b3…`) | T-222 (`1875a1ff…`) | T-213 waits for canonical lifecycle doc |
| 2 | T-214 (`57d28184…`) | T-222 (`1875a1ff…`) | T-214 waits for canonical lifecycle doc |
| 3 | T-215 (`eec95394…`) | T-222 (`1875a1ff…`) | T-215 waits for canonical lifecycle doc |
| 4 | T-217 (`2dfec97f…`) | T-222 (`1875a1ff…`) | T-217 waits for canonical lifecycle doc |
| 5 | T-219 (`7eb84a0b…`) | T-222 (`1875a1ff…`) | T-219 waits for canonical lifecycle doc |
| 6 | T-216 (`3f61a324…`) | T-215 (`eec95394…`) | T-216 waits for unified inbox path |
| 7 | T-218 (`a624b7a0…`) | T-215 (`eec95394…`) | T-218 waits for unified inbox path |
| 8 | T-220 (`29a1612d…`) | T-218 (`a624b7a0…`) | T-220 waits for request_shutdown MCP tool |
| 9 | T-220 (`29a1612d…`) | T-221 (`25630871…`) | T-220 also waits for admin force-unregister |

## Verification

The `add_task_dependency` tool performs project-scope, cycle, and self-loop validation server-side (see T-224 backend). Each call returned success, which means:

- All source and target tasks are in the same project ✅
- No self-loops introduced ✅
- No cycles created (the graph is a forest rooted at T-222 and T-221) ✅

After this PR merges, any agent that tries `start_task` on (for example) T-220 while T-218 or T-221 is still open will receive a 409 with the blockers listed.

## Scope

- No `.py`, `.ts`, `.tsx`, `.js` files touched.
- Only addition: this demo document.
- Board mutations happened via MCP, not SQL.

## Test report

| Check | Result |
|---|---|
| 9 `add_task_dependency` calls | All succeeded |
| `start_task` guard enforcement | Exercised by T-224's integration tests; not re-run here |
| Forward progress on F-48 | Backlog tasks now correctly ordered for future agents |

_No new unit or integration tests — this is a data-only change using a tool that is itself covered by T-224's test suite._
