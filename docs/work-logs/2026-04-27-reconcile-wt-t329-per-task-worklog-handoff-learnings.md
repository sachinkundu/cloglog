# Learnings — wt-t329-per-task-worklog-handoff (reconcile close-out)

Extracted from `shutdown-artifacts/work-log-T-329.md` `## Learnings` section. The agent that shipped T-329 wrote these as it landed PR #243 (per-task work-log handoff with `/clear` between tasks). The new entries marked **[FOLD]** are added to `CLAUDE.md` under the matching section; the rest are already covered by existing CLAUDE.md entries and recorded here for the historical trail.

## New durable gotchas

### Supervisor / agent lifecycle

- **[FOLD] `get_active_tasks` vs `get_my_tasks` scope difference is load-bearing.** `get_my_tasks` is scoped to the *caller's* registration. The main-agent supervisor cannot use it to ask "does worktree X still have backlog tasks?" — it returns the supervisor's own list. The supervisor's `agent_unregistered` handler MUST use `get_active_tasks` filtered by `worktree_id`. Silent-failure mode: `get_my_tasks` returns empty, supervisor concludes "no more tasks", prematurely triggers close-wave on a worktree that still had backlog work.

### Demo classifier / exemption gate (F-51)

- **[FOLD] Exemption hash must be recomputed after every commit round.** The classifier pins the exemption to a SHA256 over `git diff "$MERGE_BASE" HEAD -- . ':(exclude)docs/demos/'`. The `:(exclude)docs/demos/` pathspec keeps the hash bound to the *code* changes, not the exemption file itself — but every new commit on the branch (codex-fix round, ruff fix, etc.) shifts the diff, invalidating the stored hash. Refresh `docs/demos/<wt>/exemption.md`'s `diff_hash` after every commit round, or the next `make quality` run rejects the PR. T-329 hit this five times across codex sessions.

### Showboat / lint hygiene

- **[FOLD] Ruff N806: uppercase variables inside functions are flagged.** Test helper variables like `LIFECYCLE = REPO_ROOT / "..."` MUST be lowercase when inside a function body. Only module-level constants are exempt from N806. T-329 nearly shipped lint-clean and tripped N806 on a session-3 fix.

## Already covered by existing CLAUDE.md entries

- **Pin test absence vs documentation that names the antipattern** → already in `### Plugin hooks: YAML parsing` ("Absence-pins on antipattern substrings collide with documentation that names the antipattern").
- **Codex 5-session cap when scope expands** → already in `### Codex review on long-cycle PRs` ("Codex 5/5 cap is not an optional ceiling on factual-precision PRs").

## Residual TODOs from T-329 (filed, not closed)

- **T-NEW-b** — `src/agent/services.py:237` pipeline guard treats `review`-status predecessor as resolved only when `pr_url` is non-empty. `skip_pr=True` plan tasks have no `pr_url`, so `start_task` on the dependent impl returns 409. Documented in `worktree-agent.md` as "BACKEND GAP".
- Integration test for the full relaunch flow: simulate two backlog tasks, verify agent exits after task 1, supervisor relaunches, second session reads prior work log via the per-task work-log bootstrap.
- Offset-tracked inbox replay (analogous to `wait_for_agent_unregistered.py`) for crash recovery so missed control events (`pr_merged`, `review_submitted`) are replayed properly. Filed under T-296.
