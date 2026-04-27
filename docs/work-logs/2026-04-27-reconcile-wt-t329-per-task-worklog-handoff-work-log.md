# Aggregate Work Log — wt-t329-per-task-worklog-handoff
# Generated: 2026-04-27T14:06:10+03:00

---
# Source: work-log-T-329.md
---
task: T-329
title: "Worktree-agent: per-task work-log handoff with /clear between tasks"
pr: https://github.com/sachinkundu/cloglog/pull/243
merged_at: 2026-04-27T11:30:00Z
---

## What shipped

Replaced the multi-task session loop (agent calls `get_my_tasks` after `pr_merged` and continues) with a hard-exit-after-one-task contract. Per-task work logs (`shutdown-artifacts/work-log-T-<NNN>.md`) serve as the context handoff mechanism between sessions.

Key changes:
- **worktree-agent.md**: Work-Log Bootstrap section (reads prior logs before any work); one-task-per-session contract in spec/impl step 6 (write per-task log → build aggregate → emit `agent_unregistered` → exit); per-task work-log schema with 6 required section headers; Trigger A (pr_merged) + Trigger B (standalone no-PR task → `reason: no_pr_task_complete`) shutdown sequences
- **launch/SKILL.md**: Step 13 updated to hard-exit; `launch.sh` template accepts `$1` as optional continuation prompt; Supervisor Relaunch Flow + Continuation Prompt sections; one-task-per-session stated; `get_active_tasks` (not `get_my_tasks`) for backlog check; warns against raw `claude` (use `launch.sh` for signal trap)
- **setup/SKILL.md**: `agent_unregistered` handler — `get_active_tasks` + worktree_id filter → relaunch via `launch.sh` or close-wave
- **close-wave/SKILL.md**: Step 5b treats `artifacts.learnings` as optional/null (null for T-329 agents); Step 5d reads per-task `work-log-T-*.md` files first; `Supervisor relaunch vs close-wave boundary` documented
- **docs/design/agent-lifecycle.md**: Trigger B split (plan → continue; standalone no-PR → exit); Section 2 shutdown uses per-task log files; `agent_unregistered` event example has `"learnings": null`
- **webhook_consumers.py + services.py**: Updated `_build_message(PR_MERGED)` and shutdown message to 7-step per-task sequence; removed "call get_my_tasks and start the next task"
- **remind-pr-update.sh**: Fixed PR_NUM → TASK_NUM for work-log naming (T-42 ≠ PR #317)
- **tests**: 24 pin tests in `test_worktree_agent_one_task_per_session.py`; `test_per_task_work_log_schema.py`; `test_webhook_consumers.py::test_pr_merged_message_no_get_my_tasks`

## Files touched

- `plugins/cloglog/agents/worktree-agent.md`
- `plugins/cloglog/skills/launch/SKILL.md`
- `plugins/cloglog/skills/setup/SKILL.md`
- `plugins/cloglog/skills/close-wave/SKILL.md`
- `plugins/cloglog/skills/github-bot/SKILL.md`
- `plugins/cloglog/templates/claude-md-fragment.md`
- `plugins/cloglog/hooks/remind-pr-update.sh`
- `docs/design/agent-lifecycle.md`
- `docs/contracts/webhook-pipeline-spec.md`
- `docs/demos/wt-t329-per-task-worklog-handoff/exemption.md`
- `mcp-server/src/server.ts`
- `src/gateway/webhook_consumers.py`
- `src/agent/services.py`
- `tests/plugins/test_worktree_agent_one_task_per_session.py`
- `tests/plugins/test_per_task_work_log_schema.py`
- `tests/gateway/test_webhook_consumers.py`
- `tests/test_wait_for_agent_unregistered.py`

## Decisions

- **Supervisor-driven relaunch, not agent-driven**: Agent exits unconditionally; supervisor sees `agent_unregistered`, calls `get_active_tasks` filtered by worktree_id, decides relaunch or close-wave. Encoding "check for more tasks" in launcher bash would duplicate MCP logic the supervisor already owns.
- **`get_active_tasks` not `get_my_tasks` for supervisor**: `get_my_tasks` is scoped to the supervisor's own registration — it cannot answer "does wt-A still have backlog tasks?" Only `get_active_tasks` with worktree_id filter works.
- **`launch.sh` wrapper for continuation**: Raw `claude --dangerously-skip-permissions` bypasses the TERM/HUP/INT signal trap that calls `_unregister_fallback` via curl. Crash/close-tab in a continuation session would leave the worktree row dangling. Always relaunch through the wrapper.
- **`artifacts.learnings: null` for T-329 agents**: Learnings embedded in per-task work-log files; separate `learnings.md` superseded. Close-wave Step 5b must guard against null before opening the path.
- **Aggregate `work-log.md` still built**: Per-task logs concatenated with one-line envelope header; `artifacts.work_log` still points to the aggregate for close-wave's Step 5b path. Both old and new consumers work.
- **Task number for work-log naming, not PR number**: T-42 and PR #317 are different integers. Hook uses `<TASK_NUM>` placeholder; agent derives from active task's `number` field.

## Review findings + resolutions

**Session 1**: Absence-pin regression risk if `get_my_tasks` appears in other contexts → narrowed assertion to `"get_my_tasks and start the next task"` substring. Addressed.

**Session 2**: `launch.sh` in setup SKILL used raw `claude --dangerously-skip-permissions` without the wrapper → updated both launch and setup SKILLs to `bash '${WORKTREE_PATH}/.cloglog/launch.sh' '<prompt>'`. Hook needs TASK_NUM not PR_NUM → fixed `remind-pr-update.sh`. Missing `Do NOT use mcp__cloglog__get_my_tasks` warning in setup → added. `learnings: null` in event shape → updated lifecycle doc example. Standalone no-PR exit path missing → added `no_pr_task_complete` Trigger B branch. Addressed all.

**Session 3**: N806 ruff violation (`LIFECYCLE` and `HOOK` uppercase variables in functions) → renamed to lowercase `lifecycle` and `hook`. Test assertion `"get_my_tasks" not in msg["message"]` too broad (message now says "Do NOT call get_my_tasks") → narrowed to `"get_my_tasks and start the next task"`. Addressed.

**Session 4**: `launch.sh` template in launch SKILL used `get_my_tasks` for supervisor relaunch check → replaced with `get_active_tasks` + worktree_id filter; added `Do NOT use mcp__cloglog__get_my_tasks` warning. Addressed.

**Session 5 (cap reached)**: Spec and impl step 6 omitted building aggregate `work-log.md` before `agent_unregistered` → added build step in both places. Close-wave Step 5b tried to open null `artifacts.learnings` → guarded with "only if non-null". Added pin tests for both. Addressed. Codex 5/5 cap exhausted without `:pass:` — PR merged by operator.

## Learnings

- **Exemption hash must be recomputed after every commit round.** `git diff "$MERGE_BASE" HEAD -- . ':(exclude)docs/demos/'  | sha256sum` — the pathspec exclude keeps the hash pinned to the code, not the exemption file itself. Miss this and the quality gate fails on the next run.
- **Ruff N806: uppercase variables inside functions are flagged.** Test helper variables like `LIFECYCLE = REPO_ROOT / "..."` must be lowercase when inside a function body. Only module-level constants are exempt.
- **Pin test assertions on `not in body` collide with documentation that names the antipattern.** If the SKILL.md says "Do NOT use `get_my_tasks`" the naive assertion `"get_my_tasks" not in body` fails. Always assert the specific pattern you want absent (e.g., `"get_my_tasks and start the next task"`), not the broad token.
- **`get_active_tasks` vs `get_my_tasks` scope difference is load-bearing.** `get_my_tasks` is scoped to the supervisor's own registration. It cannot answer "does this other worktree have backlog tasks?" The supervisor's agent_unregistered handler MUST use `get_active_tasks` filtered by `worktree_id`. This is a silent failure — `get_my_tasks` returns empty and the supervisor treats it as "no more tasks", prematurely triggering close-wave.
- **Codex 5-session cap fires when scope expands across rounds.** Each imprecision in round N generates sibling findings in round N+1 as codex re-reads adjacent files. Bundle the full scope in round 1. Once cap exhausted, PR is operator-driven.

## Residual TODOs

- T-NEW-b: Pipeline guard at `src/agent/services.py::_collect_pipeline_blockers` (currently `src/agent/services.py:335-340`) treats `review`-status predecessor as resolved only when `pr_url` is non-empty. Plan tasks via `skip_pr=True` have no `pr_url`, so `start_task` on the impl task returns 409. This is documented in worktree-agent.md as "BACKEND GAP — T-NEW-b".
- Integration test for the full relaunch flow: simulate two backlog tasks, verify agent exits after task 1, supervisor relaunches, second session reads prior work log.
- Offset-tracked inbox replay (analogous to `wait_for_agent_unregistered.py`) for crash recovery so missed control events are replayed properly — currently filed as follow-up in the setup skill.

