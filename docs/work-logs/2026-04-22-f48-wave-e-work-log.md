# 2026-04-22 — F-48 Wave E work log

Two parallel worktrees targeting F-48 (agent lifecycle / worktree bootstrap). Both prioritised tasks landed.

## Scope

| Worktree | Task | PR | Title |
|---|---|---|---|
| `wt-e1-mcp-failure-rule` | T-213 | #183 | Broaden "Stop on MCP failure" rule to cover runtime tool errors |
| `wt-e2-cooperative-shutdown` | T-220 | #182 | Rewrite reconcile + close-wave skills to use cooperative shutdown flow |

## wt-e1-mcp-failure-rule / PR #183 / T-213

Commits:

```
5eeab66 docs(agent-lifecycle): address round-2 review on T-213 (PR #183)
b714a20 docs(demo): make T-213 demo script idempotent with `rm -f demo.md`
9153109 docs(agent-lifecycle): broaden "Stop on MCP failure" rule to cover runtime tool errors (T-213)
```

Files changed:
- `CLAUDE.md` — new "Stop on MCP Failure" section
- `docs/design/agent-lifecycle.md` — broadened §4.1 with runtime-tool-error / transient / unavailability cases, added `mcp_tool_error` event shape and `reason` enum
- `plugins/cloglog/templates/claude-md-fragment.md` — broadened rule text injected by `/cloglog init`
- `plugins/cloglog/skills/setup/SKILL.md`, `plugins/cloglog/skills/launch/SKILL.md`, `plugins/cloglog/agents/worktree-agent.md` — consistent rule wording
- `tests/test_mcp_failure_rule_wording.py` — byte-exact canonical-sentence-per-file backstop test
- `docs/demos/wt-e1-mcp-failure-rule/{canonical-rule.txt,demo-script.sh,demo.md}`

Behavioural change: the rule now distinguishes three cases — **startup unavailability** (emit `mcp_unavailable`, exit), **runtime tool error** (emit `mcp_tool_error{reason: …}`, halt, wait for main), **transient network error** (one backoff retry, then treat as runtime tool error). 409 guard rejections are now explicitly classified as runtime tool errors (not transient, not "advisory") — closes the loophole that had agents silently "pressing on" through a guard rejection.

Bundled decision: `pipeline_guard_blocked` (from F-48 Wave D) collapsed into `mcp_tool_error{reason: "pipeline_guard_blocked"}` — single event type with a `reason` enum is cheaper than per-case events for supervisors to pattern-match.

## wt-e2-cooperative-shutdown / PR #182 / T-220

Commits:

```
3422d60 feat(mcp): add list_worktrees; close-wave/reconcile use it for path→id mapping
dbd38c9 fix(close-wave,reconcile): address review findings on PR #182
956f749 feat(close-wave,reconcile): drive shutdown through cooperative request_shutdown + wait
```

Files changed:
- `plugins/cloglog/skills/close-wave/SKILL.md` — rewrote to call `request_shutdown` first, wait on `agent_unregistered`, fall back to `force_unregister` on timeout
- `plugins/cloglog/skills/reconcile/SKILL.md` — same cooperative path; three cases (wedged, PR-merged-not-closed, orphaned) each wired to the appropriate shutdown primitive
- `docs/design/agent-lifecycle.md` — §2 and §6 updated to describe the cooperative flow as primary, `force_unregister` as fallback
- `mcp-server/src/tools.ts`, `mcp-server/src/server.ts`, `mcp-server/src/__tests__/tools.test.ts`, `mcp-server/tests/server.test.ts` — new `list_worktrees` MCP tool wrapping `GET /api/v1/projects/{id}/worktrees` (skills need path→id mapping with branch_name, status, last_heartbeat; the board's `TaskCard` doesn't carry worktree metadata)
- `scripts/wait_for_agent_unregistered.py` — polling helper with `--since-offset` for race-window mitigation (snapshot inbox byte-offset before `request_shutdown`, pass to helper; events written between MCP call return and helper start are still in range)
- `tests/test_wait_for_agent_unregistered.py` — happy-path and timeout-fallback coverage
- `docs/demos/wt-e2-cooperative-shutdown/{demo-script.sh,demo.md}`

Behavioural change: close-wave and reconcile no longer `kill <pid>` the launcher as the primary shutdown path. They ask the worktree to unregister itself via `request_shutdown(worktree_id, reason)`, wait up to 60s for `agent_unregistered` on the main inbox, and only fall back to `force_unregister` + `zellij close-tab` on timeout. This preserves the worktree's own `agent_unregistered` emission (artifacts paths, tasks_completed) which was being bypassed under the kill-path.

## Learnings & issues

Codified from both shutdown-artifacts/learnings.md files. Candidates for CLAUDE.md — to be integrated in the post-processor step:

1. **`showboat verify` runs without the dev DB.** Demo scripts that invoke `uv run pytest` break in CI / on hosts without Postgres running — `tests/conftest.py`'s session-autouse fixture connects to localhost:5432 on pytest start. Fix pattern: bypass pytest, import the test module directly (`python3 -c "import sys; sys.path.insert(0, 'tests'); import test_foo as t; t.test_one()"`). Worth adding to `plugins/cloglog/skills/demo/SKILL.md` determinism section.
2. **`showboat init` refuses to overwrite.** Docs-only demos where `demo.md` is committed must `rm -f "$DEMO_FILE"` before `uvx showboat init` in `demo-script.sh` — otherwise re-running `make demo` on the same checkout fails. Caught in PR #183 R1.
3. **Canonical-sentence fixtures need no trailing newline.** `grep -Ff file target` with an empty line in the pattern file matches every line. Write the fixture with `printf` (no trailing newline) or filter via `grep -v '^$' file | grep -Ff - target`.
4. **When broadening a rule, collapse narrow-case events into a `reason` field.** `mcp_tool_error{reason: "pipeline_guard_blocked"}` > separate events. Supervisors pattern-match on a single shape.
5. **Launcher `_api_key()` fallback chain is a T-214 risk.** Env → `.env` → `.mcp.json` fallbacks re-create the secret-placement problem T-214 pinned down. Match `mcp-server/src/credentials.ts` exactly — env → `~/.cloglog/credentials` only. (E1 fixed this in the generated launcher template.)
6. **`get_board`'s `TaskCard` doesn't carry worktree metadata.** Skills doing worktree lifecycle management must call `list_worktrees` (E2 added this MCP tool), not parse `get_board`. Board is task-view, not worktree inventory.
7. **Supervisor inbox is ephemeral** — truncated by `plugins/cloglog/hooks/agent-shutdown.sh` when the main-agent session ends. Anything the supervisor needs across restarts must come from backend state via MCP, never inbox scanning.
8. **Race window between MCP-call-return and shell-subprocess-start.** A skill that "calls an MCP tool then runs a shell helper to poll for a response event" must capture the inbox byte-offset BEFORE the MCP call, not at helper entry. Applied in `scripts/wait_for_agent_unregistered.py --since-offset`.
9. **Reviewer caps at 2 rounds.** `cloglog-codex-reviewer[bot]` returns "maximum of 2 bot reviews" on round 3 — plan substantive replies per round.

## Board state after Wave E

All F-48 prioritised work consumed. Remaining F-48 backlog (not yet prioritised): T-256 (apply T-244 demo port fix), T-257 (broaden npm-install trigger), T-258 (worktrees auth contract), T-259 (yaml fallback in on-worktree-create.sh). Those are safe quick-wins for a future wave.

## State after this wave

- `request_shutdown` + `agent_unregistered` round-trip is the primary shutdown path in both `close-wave` and `reconcile`. `force_unregister` is the fallback (timeout-gated, logged).
- `mcp_tool_error{reason, tool, error, task_id}` is the standard runtime-error inbox event; startup unavailability still uses `mcp_unavailable`.
- `list_worktrees` MCP tool is available for any future skill needing worktree metadata.
- Canonical "Stop on MCP Failure" text is consistent across CLAUDE.md, plugin fragments, and agent/setup/launch skills — enforced by the byte-exact backstop test.
