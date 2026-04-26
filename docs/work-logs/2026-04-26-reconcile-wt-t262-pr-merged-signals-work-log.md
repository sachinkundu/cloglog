# Work Log: wt-t262-pr-merged-signals

**Date:** 2026-04-26
**Worktree:** wt-t262-pr-merged-signals
**Task:** T-262 — Enrich agent lifecycle signals (`pr_merged_notification` + `prs` map)
**PR:** https://github.com/sachinkundu/cloglog/pull/220 (MERGED)

## Stakeholder outcome

Worktree agents now surface PR merges to the supervisor's inbox in real time, and the agent_unregistered sign-off carries PR URLs per task. The visibility gap that motivated T-262 (2026-04-23 PR #187 merge — wt-f47 consumed the event silently, supervisor had to grep `gh pr list`, wt-f48 idled waiting for a hand-forwarded signal) is closed.

## Commits

- `dc7f001` feat(lifecycle): T-262 pr_merged_notification + prs map in agent_unregistered
- `b04f2b8` docs(demos): T-262 classifier exemption (round 1)
- `5e44795` feat(lifecycle): T-262 propagate to github-bot/claude-md/worktree-agent docs (Codex round 1)
- `d5026ef` docs(demos): T-262 round-2 exemption refresh
- `ebd58d3` feat(agent): T-262 expose pr_url + number on TaskInfo (Codex round 2)
- `72e84ce` docs(demos): T-262 real demo (TaskInfo exposes number + pr_url)
- `a32614f` fix(agent): T-262 propagate TaskInfo fields to register/complete responses (Codex round 3)
- `533c2ad` fix(types,docs): T-262 round 4 — regen frontend types + propagate to impl-task path

## Files changed (PR #220)

- `docs/design/agent-lifecycle.md` — §1 Trigger A, §2 step 5 example, §6 outbound events table
- `plugins/cloglog/hooks/agent-shutdown.sh` — best-effort `prs` enrichment via `gh pr list --state merged --head`
- `plugins/cloglog/skills/launch/SKILL.md` — agent prompt template for both pr_merged and shutdown paths
- `plugins/cloglog/skills/github-bot/SKILL.md` — PR Event Inbox section
- `plugins/cloglog/templates/claude-md-fragment.md` — PR polling and shutdown sections
- `plugins/cloglog/agents/worktree-agent.md` — spec, impl, shutdown task blocks
- `src/board/templates.py` — close-off task description references the prs map
- `src/agent/schemas.py` — TaskInfo gains `number`, `pr_url`, `artifact_path`
- `src/agent/services.py` — register() and complete_task() hand-built dicts mirror the full TaskInfo shape
- `docs/contracts/baseline.openapi.yaml` — TaskInfo schema entries updated
- `frontend/src/api/generated-types.ts` — regenerated to match contract
- `tests/test_agent_shutdown_hook.py` — pin `prs` field on hook output
- `tests/test_agent_lifecycle_pr_signals.py` — pin spec, skill content, secondary instruction sources, TaskInfo schema fields
- `tests/agent/test_unit.py` — pin reconnect path through RegisterResponse.model_validate
- `docs/demos/wt-t262-pr-merged-signals/` — real demo + script

## Codex review rounds

5 sessions; first 4 returned `:warning:` with concrete findings, session 5 approved.

| Round | Finding | Fix |
| --- | --- | --- |
| 1 | Protocol propagated only to launch SKILL; github-bot SKILL, claude-md-fragment, worktree-agent still describe old flow | Updated all three; added cross-doc pin test |
| 2 | TaskInfo doesn't expose `pr_url` or task number — documented prs-map construction is unimplementable | Added `number`, `pr_url`, `artifact_path` to TaskInfo + OpenAPI baseline; added pin test |
| 3 | AgentService.register() hand-builds current_task without `number` (now required) — reconnect returns 500 | Mirror full TaskInfo shape in both hand-built dicts; pin test round-trips through RegisterResponse.model_validate |
| 4 | worktree-agent.md impl-task block (line 83) still old; frontend generated-types.ts out of sync with contract | Updated impl-task block; regenerated TypeScript types |
| 5 | Approved (`:pass:`) | — |

## Quality gate

- `make quality` green every iteration (864 tests, 88% coverage, contract clean, demo verified)
- 5 new tests pin the protocol contract + secondary instruction docs + TaskInfo schema + reconnect response shape

## Notes for future agents

- The hook backstop (`agent-shutdown.sh`) emits `prs: {}` when `gh pr list` is unavailable. The agent-side emit (this very script) is the rich path — supervisors prefer the agent's record when both lines are present.
- The `prs` map is keyed at `f"T-{row.number}"` from `get_my_tasks()` rows; rows without `pr_url` are omitted, never mapped to `null`.
- Pre-existing frontend `tsc -b` errors (codex_review_picked_up drift, missing retire/reorder events on EventType, useSearch unused var) are unrelated to T-262 and reproduce on origin/main. Out of scope; flagged in the round-4 reply for a future cleanup task.
