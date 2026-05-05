# Work log — wt-t394-mcp-position-reorder

Closed: 2026-05-05.
Wave name: t394-mcp-position-reorder (single-task wave).

## Worktrees

| Worktree | Branch | Tasks | PR | Shutdown path |
|----------|--------|-------|----|---------------|
| wt-t394-mcp-position-reorder | wt-t394-mcp-position-reorder | T-394 | [#323](https://github.com/sachinkundu/cloglog/pull/323) | cooperative — `agent_unregistered` received 2026-05-05T08:03:55+03:00 (`reason=pr_merged`) |

## What shipped

From `shutdown-artifacts/work-log-T-394.md` (consolidated before worktree teardown):

Three new MCP tools wrapping the existing reorder HTTP endpoints already exercised by the frontend `BacklogTree`:

- `mcp__cloglog__reorder_epics({ items })` → POST `/api/v1/projects/{pid}/epics/reorder`
- `mcp__cloglog__reorder_features({ epic_id, items })` → POST `/api/v1/projects/{pid}/epics/{epic_id}/features/reorder`
- `mcp__cloglog__reorder_tasks({ feature_id, items })` → POST `/api/v1/features/{feature_id}/tasks/reorder`

`items` carry the new absolute positions (`{id, position}[]`); the frontend convention is `i * 1000` so manual gaps stay available between siblings. Each tool is project-scoped via `requireProject()` (consistent with the other board-mutation tools); errors surface through `wrapHandler` as `isError: true`.

PR #323, merge commit `f4c1af9e`, merged 2026-05-05T05:02:49Z. Three CI checks (`init-smoke`, `ci`, `e2e-browser`) green; codex returned `:pass:` first session; auto-merge fired with reason `merge`.

### Files touched

- `mcp-server/src/tools.ts` — three handlers + `ToolHandlers` interface entries.
- `mcp-server/src/server.ts` — three `server.tool(...)` registrations.
- `mcp-server/src/__tests__/tools.test.ts` — +3 unit tests pinning method/URL/body.
- `mcp-server/tests/server.test.ts` — +6 tests covering tool exposure, not-registered guard, success paths, error surfacing.
- `docs/demos/wt-t394-mcp-position-reorder/{demo.md,demo-script.sh}` — Showboat demo built against the dist with a mock `CloglogClient`.

### Decisions

- **No new HTTP routes.** Backend reorder endpoints already exist; frontend uses them. Wrapping at the MCP layer is purely additive on the agent surface.
- **Project-scoped guard, not worktree-scoped.** `requireProject()` rather than `requireRegistered()` — reordering operates on project data, not on a worktree-bound active task.
- **No relative `before/after` helpers.** Deferred per "wrap absolute-position contract first; add relative helpers only on friction." Frontend uses absolute positions; supervisor has the same view.
- **Demo via mock `CloglogClient` + built dist.** Deterministic proof that wrapper layer maps argument shape → URL without needing a live backend.

## Shutdown summary

- `agent_unregistered` received cleanly with `reason=pr_merged` and per-task work log at `shutdown-artifacts/work-log-T-394.md`. Cooperative path.
- **Launcher survived `unregister_agent`** — bash launcher PID 1886296 + claude PID 1886304 were still alive when close-wave Step 6 ran `pgrep`. `/tmp/agent-shutdown-debug.log` had no `wt-t394` entries (trap never fired). The zellij tab close in Step 6 killed claude via SIGHUP and the launcher's `wait` returned naturally — no trap, but no surviving process either. Evidence captured in `T-428` (exit-on-unregister hook didn't fire); this is the second confirmed recurrence after T-376/T-408.
- **Launch.sh prompt rendering bug.** The running claude was invoked with `Read /AGENT_PROMPT.md and begin.` (literal `/AGENT_PROMPT.md`) — `@@WORKTREE_PATH@@` was sed-substituted with empty during launch. Root cause: when the launch SKILL's bash block was transcribed into the supervisor's Bash tool call, `_sed_escape_replacement`'s `printf '%s' "$1"` lost the `$1` reference (T-353 class — heredoc/string round-trip drift). The supervisor patched the rendered file in place and re-prompted via `zellij action write-chars` with the absolute path. Pinned by T-354 (already prioritized): drop the SKILL-embedded heredoc entirely; renders the launcher from a tracked file with deterministic substitution.

## Learnings & invariants routed

No new invariants for `docs/invariants.md` — both shutdown observations land in already-filed tasks (T-354, T-428). The launch SKILL refactor task created earlier this session (T-431) overlaps with T-354's scope; reconciled below.

### Process notes (route to F-56 Plugin SKILL Hygiene context, not CLAUDE.md)

- **Inbox monitor delivered `agent_started` correctly**, but the supervisor needs a deadline-armed bg task per launch to act on absence-of-event (the wt-t394 launch sat ~7 min without `agent_started` while the supervisor passively observed). Filed conceptually under the "inbox actor" thread under E-10 Source Cleaning; concrete script `wait-for-agent-started.sh` is already listed as extraction #4 on T-431.
- **Supervisor-side agent_token can 401 mid-session** — `add_task_note` on T-428 returned `401 Invalid agent token` despite an earlier successful `register_agent`. Re-registering refreshed the token. Likely cause: token rotation or a reconcile pass force-unregistering the supervisor's session while it was idle. Worth filing as a follow-up if it recurs.

## State after this wave

- T-394 done (PR #323 merged, MCP tool surface extended with three reorder handlers, dist rebuilt and broadcast).
- F (Drag-and-Drop Backlog Prioritization) gains its MCP surface; agents can now reprioritize the same way the frontend does.
- T-428 (exit-on-unregister hook gap) gained a recurrence; T-354 (drop SKILL-embedded heredoc) gained a recurrence. Both remain prioritized.
- New scaffolding from this session for follow-up: E-10 Source Cleaning, F-56 Plugin SKILL Hygiene, T-430 audit, T-431 launch refactor (overlap with T-354 to reconcile next).
