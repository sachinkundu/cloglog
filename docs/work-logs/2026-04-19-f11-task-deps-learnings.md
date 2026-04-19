# Learnings — wt-task-deps

**Date:** 2026-04-19

## What went well

- **Pipeline ordering held.** T-223 (spec) → T-226 (plan) → T-36 (task) → T-224 (impl) → T-225 (dogfood) matched the AGENT_PROMPT order exactly. The backend's pipeline guard rejected out-of-order `start_task` attempts without incident.
- **Codex reviewer caught real spec/plan issues.** Both T-223 and T-226 went through two revision rounds before merge. Worth the cycles — the final spec is coherent about guard ordering and error payload shape.
- **Small dogfood PRs work.** T-225 shipped as a 1-file doc-only PR whose entire purpose was an audit trail of nine MCP calls. Codex returned `:pass:` after cross-referencing the claims against T-224's implementation. Low friction, high signal.
- **Data + API + MCP tool + guard in one PR (T-224)** kept the migration + schema + consumer story coherent. Splitting that across PRs would have forced temporary backwards-compat shims.

## Issues encountered

### `AGENT_PROMPT.md` "wait for board to show task as done" is unreachable
- Agents do NOT receive an inbox event when the user moves a card review → done. That transition emits only to the dashboard SSE bus. If agents wait on it, they wait forever.
- Main agent had to send a `protocol_correction` message to unblock this shutdown.
- **Fix:** update the plugin's agent-prompt template — exit condition for the last task should be `pr_merged` only (plus artifact upload for spec/plan tasks). Review→done is a human UI concern, not an agent state-machine concern.

### `get_board` responses exceed tool-output limit
- A raw `get_board()` (no filters) returned 109k chars — past the tool-output ceiling — and had to be redirected to a file. Even filtered by epic (Operations & Reliability), the response was 65k chars.
- Workaround used: `Grep` against the saved file to extract task UUIDs and `number` fields.
- **Fix candidate:** add a `fields` parameter to `get_board` (e.g. return only `id,number,title,status,feature_id`) for cases where the caller just needs an index.

### Shutdown artifact templates are stale
- `shutdown-artifacts/work-log.md` and `learnings.md` existed from a prior worktree (`wt-depgraph`, 2026-04-05). They were skeletons with no content and had to be fully overwritten.
- **Fix candidate:** the launch script should either seed these files with the current worktree name and an empty template, or delete them at launch so the agent creates fresh.

### MCP dist rebuild coordination
- After T-224 merged, `mcp-server/dist/` had to be rebuilt on main before T-225 could ToolSearch-load `add_task_dependency`. Main agent sent a `correction_from_main` / `correction_retraction` pair to clarify the state (initially thought PR #149 hadn't merged, then retracted).
- **Fix candidate:** a post-merge hook that rebuilds `mcp-server/dist` and broadcasts `mcp_tools_updated` to agents with the new tool names, so downstream dogfood tasks don't need a session restart to pick them up.

### `get_board` does not expose `blockedBy` on task rows
- After the nine `add_task_dependency` calls, a spot-check via `get_board` did not show the new edges anywhere in the response. The tool-level confirmation ("Task dependency added: X blocked_by Y") is currently the only agent-visible proof.
- Board JSON includes `status`, `priority`, `pr_url`, `pr_merged`, etc. — but not the adjacency list.
- **Fix candidate:** surface `blocked_by: [task_id]` (and/or `blocks: [task_id]`) on each task row in `get_board`, scoped to within-feature edges so payload doesn't explode. Enables agents to self-verify after running mechanical graph-encoding tasks like T-225.

## Suggestions for `CLAUDE.md` or plugin updates

- **Agent prompt template:** drop "AND for board to show task as `done`" from the wait condition. Exit on `pr_merged` + (artifact_report if spec/plan).
- **Launch script:** reset `shutdown-artifacts/*.md` to empty-or-template for each new worktree.
- **`get_board` ergonomics:** (a) add `fields` projection; (b) include `blocked_by` in the task row; (c) include `feature_id` filter (currently only `epic_id` is supported — had to filter in grep).
- **MCP rebuild broadcast:** after a merge that touches `mcp-server/src/`, the main agent (or a hook) should rebuild dist and notify any waiting dogfood agents.
