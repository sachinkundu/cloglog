# Wave: F-48 Wave C — 2026-04-21

F-48 "Agent Lifecycle Hardening — Graceful Shutdown & MCP Discipline" Wave C.
Two parallel worktree agents (C1 and C2) implemented T-216, T-243, and T-244.
Both PRs merged cleanly within ~25 minutes of each other.

## Worktrees closed

| Worktree           | Branch             | PR   | Merged (UTC)          | Tasks         |
|--------------------|--------------------|------|-----------------------|---------------|
| wt-c2-mcp-rebuild  | wt-c2-mcp-rebuild  | #172 | 2026-04-21T06:13:56Z  | T-244         |
| wt-c1-inbox-docs   | wt-c1-inbox-docs   | #173 | 2026-04-21T06:37:06Z  | T-216, T-243  |

## PR #172 — T-244: auto-rebuild mcp-server dist + mcp_tools_updated broadcast

The long-standing gap from 2026-04-19 (`mcp-server/dist/` staying stale after
a merge and already-running Claude sessions caching the MCP tool list at
startup) is now closed. A main-agent script rebuilds `dist/` when a merge
touches `mcp-server/src/**` and writes a `mcp_tools_updated` JSON line to
every online worktree's `.cloglog/inbox` plus the main inbox. Downstream
agents know they need a session restart; the canonical lifecycle doc
(T-222) gained a §6 "Restart-for-new-tools protocol" section.

Commit on the feature branch: `4a83dc8 feat(mcp): T-244 auto-rebuild
mcp-server dist + mcp_tools_updated broadcast` plus one review-fix commit
`7a90a53 fix(sync_mcp_dist): send X-Dashboard-Key on worktree fetch`.

Files touched (7 files, +1026 / −7):

- `Makefile` — `make sync-mcp-dist` wrapper target.
- `scripts/sync_mcp_dist.py` (new, 280 lines) — `run()` snapshots tool
  names in `mcp-server/dist/server.js`, rebuilds via `npm run build`,
  diffs, fetches online worktrees from `/api/v1/projects/{pid}/worktrees`
  with `X-Dashboard-Key`, and appends the event to each inbox.
- `tests/test_sync_mcp_dist.py` (new, 288 lines) — 10 tests covering
  `extract_tool_names`, `build_event`, `broadcast`, `inbox_paths_for`,
  `fetch_online_worktree_paths`, and the full `run()` flow.
- `plugins/cloglog/skills/close-wave/SKILL.md` — new step 9.5 instructing
  the main agent to run `make sync-mcp-dist` between `git pull` and
  `make quality`.
- `docs/design/agent-lifecycle.md` — §6 now implemented, not "pending".
- `docs/demos/wt-c2-mcp-rebuild/{demo.md,demo-script.sh}` — proof-of-work.

Codex findings addressed during review:

- Round 1 (pre-merge): `sync_mcp_dist.py` hit `/projects/{id}/worktrees`
  with bare `httpx.get` and silently got a 403. Fixed by sending
  `X-Dashboard-Key` explicitly (commit `7a90a53`).
- Round 1: demo hardcoded mock-server port `61244`, vulnerable to
  collision. C2 staged a follow-up patch (`t244-demo-port-fix.patch`) to
  bind port 0 and write the OS-chosen port to a shared file. PR #172 was
  already merged before that patch could land; the patch is preserved at
  `docs/work-logs/artifacts/t244-demo-port-fix.patch` and tracked as
  **T-256**.

## PR #173 — T-216 + T-243: unify inbox path + emit `agent_unregistered`

Plugin docs and skills no longer reference the dead
`/tmp/cloglog-inbox-{worktree_id}` path (T-215 already fixed the backend
write path in Wave B; C1 finished the doc/skill surface). The shutdown
protocol now requires every agent to emit a structured
`agent_unregistered` event to the main inbox before `unregister_agent`;
`plugins/cloglog/hooks/agent-shutdown.sh` is the backstop that fires it
from captured context if the agent forgets.

Commits on the feature branch:

- `23a0... fix(plugin-docs): T-216 + T-243 unify inbox path + emit agent_unregistered event` (bulk work)
- `3ee2e4d fix(plugin-docs): review findings — backend-gap disclosure + shutdown handoff in github-bot`
- `ae494f7 fix(plugin-docs): review round 2 — consumer gap disclosure + drift-proof demo`

Files touched (9 files, +556 / −51):

- `plugins/cloglog/agents/worktree-agent.md`,
  `plugins/cloglog/templates/claude-md-fragment.md`,
  `plugins/cloglog/skills/launch/SKILL.md` — `.cloglog/inbox` everywhere;
  `/tmp/cloglog-inbox-*` is gone from `plugins/`.
- `plugins/cloglog/skills/github-bot/SKILL.md` — shutdown-handoff note
  (pr_merged event → emit agent_unregistered before unregister).
- `plugins/cloglog/hooks/agent-shutdown.sh` — backstop emitter using
  `jq -cn` (not `printf`) for JSON correctness.
- `tests/test_agent_shutdown_hook.py` (new, 205 lines) — covers the
  backstop + idempotency.
- `docs/design/agent-lifecycle.md` — extended §5 with the
  `agent_unregistered` contract and two inline gap disclosures:
  - **BACKEND GAP — T-NEW-b**: plan-task `skip_pr=True + report_artifact`
    flow hits a 409 against the live pipeline guard. Agent mitigation:
    emit `pipeline_guard_blocked` and stop, let main advance.
  - **CONSUMER GAP — T-220**: the cooperative-shutdown flow's consumer
    side is Wave E's job.
- `docs/demos/wt-c1-inbox-docs/{demo.md,demo-script.sh}` — proof-of-work.

Codex findings addressed during review:

- Round 1: a count-based demo assertion (`canonical_path_files=8`) was
  brittle — any unrelated future doc mentioning `.cloglog/inbox` would
  bump the count. Replaced with per-file OK/FAIL booleans scoped to the
  audited files.
- Round 1: the initial doc reverted to a known-broken flow because the
  new flow hit a backend guard. Revised to keep the target state AND
  add an explicit BACKEND GAP disclosure with mitigation guidance.
- Round 2: consumer-side gap (T-220) surfaced and was labelled.

## Learnings & Issues

Post-merge `make quality` on main after both merges (run on this
close-wave branch): **628 passed, 1 xfailed** (pre-existing
`pr_url_reuse_blocked_cross_feature`), **91.06 %** coverage, contract
compliant, demo step correctly skipped ("docs-only branch"), MCP server
tests pass in 379 ms. No integration fixes required.

**Four durable rules promoted to `CLAUDE.md`:**

1. **The cloudflared tunnel is systemd-managed, not a `make prod`
   child process.** This was my mistake, not the wave agents': PR #174
   auto-started/killed cloudflared from `make prod`/`make prod-stop`,
   which would tear down the documented systemd service on stop. Caught
   by codex [HIGH] on #175 and @sachinkundu's "why not use the systemd
   services?" comment. PR #176 reverted the coupling and wired
   `scripts/preflight.sh` into `make prod` (same pattern `make dev:102`
   uses). Rule added under *Runtime & Deployment Assumptions*.
2. **Inside a worktree, `git rev-parse --show-toplevel` returns the
   worktree path, not the main clone.** The shutdown hook's first cut
   used `--show-toplevel` to find the supervisor inbox, which silently
   wrote to its own worktree's inbox instead. Correct idiom:
   `dirname "$(git rev-parse --git-common-dir)"`. C1's learning #4.
3. **Bundled-PR task sequencing.** An agent assigned two tasks that
   ship as one PR cannot hold both `in_progress`/`review` — the backend
   single-active-task guard rejects. C1's T-216 + T-243 sequence lands
   in CLAUDE.md under *Cross-Context Integration*.
4. **Target-state docs must label and link their gaps.** When a doc
   describes a flow dependent on unlanded backend/consumer work, keep
   the target state AND add a **BACKEND GAP — T-NNN** block that names
   the file+line, the tracking task, and the operational mitigation.
   Pattern born from T-216/T-243 round 1+2 findings.

Also added:

- **Demo proofs capture OK/FAIL booleans, not repo-wide counts** — under
  *Proof-of-Work Demos*.

**Three follow-up tasks created during Wave C processing (all under F-48):**

- **T-256** — Apply the `t244-demo-port-fix.patch` staged by C2 (demo
  script port collision fix). Preserved at
  `docs/work-logs/artifacts/t244-demo-port-fix.patch`.
- **T-257** — Broaden `.cloglog/on-worktree-create.sh` `npm install`
  trigger: the `wt-mcp*` pattern is too narrow. Any worktree touching
  `mcp-server/` needs `node_modules`; both C1 and C2 hit this.
- **T-258** — Make `/api/v1/projects/{id}/worktrees` auth contract
  unambiguous: either make the endpoint truly public for dashboard reads
  or document the `X-Dashboard-Key` requirement loudly. C2's initial cut
  of `sync_mcp_dist.py` silently 403'd because the CLI's implicit
  env-passthrough made the rule feel optional.

**Outstanding (flagged for next pass, not auto-created):**

- The `BACKEND GAP — T-NEW-b` placeholder in `docs/design/agent-lifecycle.md`
  needs a proper board task. The gap is: plan-task
  `update_task_status(status="review", skip_pr=True)` + subsequent
  `report_artifact()` hits a 409 against the pipeline guard. The fix is
  backend-side (auth check order or guard relaxation) and belongs to F-48.

## State After This Wave

- **MCP dist is self-maintaining.** Any merge that changes
  `mcp-server/src/**` triggers a rebuild + `mcp_tools_updated` broadcast
  to all online worktree inboxes + main inbox. The T-224→T-225 incident
  class is closed.
- **Shutdown protocol is observable.** Every agent emits a structured
  `agent_unregistered` event to the main inbox before unregistering;
  the SessionEnd hook backstops it if the agent forgets. The 2026-04-19
  wt-task-deps silent shutdown is no longer possible.
- **Plugin docs are consistent.** Zero references to the dead
  `/tmp/cloglog-inbox-*` path under `plugins/`. The canonical lifecycle
  doc (`docs/design/agent-lifecycle.md`) is now the single source of
  truth end-to-end; the skills and AGENT_PROMPT template defer to it.
- **Infra clean.** Both worktrees removed, local + remote branches
  deleted, zellij tabs closed. Only the main tab remains.
