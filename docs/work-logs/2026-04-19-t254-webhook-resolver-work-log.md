# T-254 Work Log — Webhook Resolver Crash Fix

**Task:** T-254 — Webhook resolver crashes on issue_comment: empty head_branch matches all online worktrees
**Worktree:** wt-webhook-resolver
**PR:** https://github.com/sachinkundu/cloglog/pull/157 (merged)
**Final commit:** 06738bc

## Problem

Every `issue_comment` webhook crashed `AgentNotifierConsumer` with `sqlalchemy.exc.MultipleResultsFound`. Two stacked bugs:

- **A (data):** `cloglog-mcp` did not send `branch_name` on register, so every live worktree row carried `branch_name=''`.
- **B (code):** `issue_comment` webhooks arrive with `head_branch=''`. The resolver's branch fallback ran `WHERE branch_name='' AND status='online'`, matching every online row at once → `scalar_one_or_none()` → crash.

## Fix

**Architecturally-correct split** after reviewer feedback:

| Layer | Change |
|---|---|
| `mcp-server/src/tools.ts` | New `deriveBranchName()` runs `git symbolic-ref --short HEAD` in-VM (where the worktree actually lives) and `register_agent` sends `branch_name` on the wire. |
| `src/agent/services.py` | `register` is a pure pass-through — no filesystem probing on the host. |
| `src/agent/repository.py` | `upsert_worktree` does not overwrite an existing `branch_name` with empty on reconnect (defensive guard). `get_worktree_by_branch('')` returns `None` (belt-and-suspenders). |
| `src/gateway/webhook_consumers.py` | `_resolve_agent` short-circuits on empty `head_branch` before the branch fallback. |
| `src/alembic/versions/c7d9e0f1a2b3_backfill_worktree_branch_names.py` | Additive-only backfill — populates `branch_name` where the path happens to be host-visible (dev mode). Never flips rows to `offline`; ghost cleanup is F-48's job (T-220/T-221). |
| `docs/demos/wt-webhook-resolver/demo-script.sh` | Normalizes slashes in `$BRANCH` so `docs/demos/${BRANCH//\//-}/` matches `scripts/check-demo.sh` discovery. |

## Review Cycle

1. **Round 1 (initial PR, a21a868):** Reviewer flagged that the backend ran `git` on VM-local paths, which is wrong under the documented deployment model (`docs/ddd-context-map.md` — cloglog runs on host, agents in Lima VMs). Moved derivation into `cloglog-mcp`, reverted backend to pass-through, made migration additive-only (commit 5d1c036).
2. **Round 2 (5d1c036):** Reviewer flagged a demo-script regression that would break `make demo-check` on slash-named branches. Fixed with `${BRANCH//\//-}` normalization (commit 06738bc).
3. **Merged:** 06738bc.

## Test Delta

- **Backend (562 pass, 1 xfailed pre-existing):**
  - `TestResolveAgent::test_resolve_empty_head_branch_returns_none_with_multiple_online_worktrees` — end-to-end resolver regression guard.
  - `TestAgentRepositoryBranchLookup::test_get_worktree_by_branch_empty_string_returns_none` — repository-layer regression guard.
  - `TestAgentService::test_register_stores_branch_name_from_caller` — pins backend pass-through contract.
  - `TestAgentService::test_register_reconnect_preserves_branch_when_caller_sends_empty` — pins defensive upsert guard.
- **MCP server (54 pass):**
  - `register_agent derives branch_name via git and POSTs both` — pins wire payload contract with a real git repo.
  - `register_agent sends empty branch_name when the path is not a git repo` — fallback path.
  - `deriveBranchName returns "" on detached HEAD` — pins `symbolic-ref` choice over `rev-parse --abbrev-ref`.

## Verification Evidence

Coverage 90.85% (above 80% gate). Demo `showboat verify` byte-exact. Migration dry-ran against dev DB during development: 4 rows backfilled with resolved branches, others left untouched for organic self-heal. Final query post-merge should report `0` online worktrees with empty `branch_name`.

## Files Touched

- `mcp-server/src/tools.ts`
- `mcp-server/src/__tests__/tools.test.ts`
- `mcp-server/tests/server.test.ts`
- `src/agent/services.py`
- `src/agent/repository.py`
- `src/gateway/webhook_consumers.py`
- `src/alembic/versions/c7d9e0f1a2b3_backfill_worktree_branch_names.py` (new)
- `tests/agent/test_unit.py`
- `tests/gateway/test_webhook_consumers.py`
- `docs/demos/wt-webhook-resolver/demo-script.sh` (new)
- `docs/demos/wt-webhook-resolver/demo.md` (new, generated)
- `docs/demos/wt-webhook-resolver/probe.py` (new)
