# wt-f48-spec — work log

**Agent:** worktree agent for T-222 (F-48 Wave A, spec task)
**Worktree:** `wt-f48-spec` / worktree_id `15540701-f07b-48bc-a74d-5fc48283e7cc`
**Session:** 2026-04-19, single run, single task.

## Scope

T-222 — "Canonical agent lifecycle protocol doc — single source of truth" under
F-48 (Agent Lifecycle Hardening — Graceful Shutdown & MCP Discipline). Spec
task, no code changes.

## Timeline

1. Registered via `mcp__cloglog__register_agent`, started inbox monitor on
   `<worktree_path>/.cloglog/inbox`, echoed `agent_started` to the main inbox.
2. `start_task` on T-222.
3. Read the F-48 feature payload via `get_board(epic_id=..., exclude_done=true)`
   (piped to file — payload exceeded MCP output limit, expected) and each
   referenced sibling task (T-215, T-216, T-217, T-218, T-219, T-220, T-221,
   T-243, T-244).
4. Read the four existing documents this spec supersedes:
   `plugins/cloglog/skills/launch/SKILL.md`,
   `plugins/cloglog/agents/worktree-agent.md`,
   `plugins/cloglog/templates/claude-md-fragment.md`,
   `plugins/cloglog/skills/github-bot/SKILL.md`. Catalogued their
   contradictions.
5. Checked concrete backend numbers for Section 5: `heartbeat_timeout_seconds
   = 180` (`src/shared/config.py`), sweep interval 60 s
   (`src/agent/scheduler.py`), `request_shutdown` currently writes to
   `/tmp/cloglog-inbox-{worktree_id}` (T-215's migration target).
6. Drafted `docs/design/agent-lifecycle.md` in one pass — six required
   sections, See-also block, Callers-to-audit block. Used the brainstorming
   skill to structure but skipped the interactive Q&A flow per the
   worktree-agent autonomy rule.
7. Ran `make quality`. First run failed on missing `respx` dev dep
   (pre-existing: the new `tests/gateway/test_{cli,github_token,review_engine}.py`
   import it, but the worktree's uv env hadn't synced yet). `uv sync
   --all-extras` resolved it. Second run: demo missing. Produced demo via
   `cloglog:demo` skill (Showboat structural proof with six
   `grep`/`sed`/`wc` blocks). Third run: clean.
8. Pre-PR file audit: excluded `.mcp.json` (inherited dirty state —
   `http://localhost:8001` → `http://127.0.0.1:8001`, unrelated to T-222).
9. Committed via bot identity, pushed, opened PR #152 with Demo + Test
   Report + Changes sections in the canonical order.
10. `update_task_status` to `review` with PR URL.
11. First review (cloglog-codex-reviewer[bot], COMMENTED): infra failure
    ("bwrap: loopback"); no actionable feedback. Added task note, stayed in
    review.
12. Second review (cloglog-codex-reviewer[bot], COMMENTED): two substantive
    findings verified against live code:
    - **MEDIUM** — main-agent inbox path is project-root-relative
      (`${PROJECT_DIR}/.cloglog/inbox` per
      `plugins/cloglog/hooks/session-bootstrap.sh`), not the hardcoded
      `/home/sachin/code/cloglog` I used. Alt checkouts would write to the
      wrong tree.
    - **HIGH** — plan-task shutdown in my spec (via `report_artifact`) is
      not satisfiable by the shipped runner: `services.py:516` requires
      `status == "review"`; `services.py:422` requires `pr_url` or
      `skip_pr=True`; `worktree-agent.md` says plan tasks commit locally
      with no PR. Plus `services.py:237` predecessor-resolution requires
      `pr_url` even for `skip_pr`-reviewed tasks, so even with
      `skip_pr=True` the downstream impl would stay blocked.
13. Moved task back to `in_progress`. Revised the spec:
    - New "Paths and discovery" subsection at the top of Section 3 with a
      two-row table explaining worktree-inbox vs main-inbox resolution.
    - Replaced every hardcoded `/home/sachin/code/cloglog/.cloglog/inbox`
      with `<project_root>/.cloglog/inbox`, linked to the new subsection.
    - Split Section 1's decision algorithm into Trigger A (`pr_merged`) and
      Trigger B (local-finish for no-PR tasks) with an explicit
      `update_task_status(..., review, skip_pr=True)` step in Trigger B.
    - Added a new step 2 in Section 2 ("Move to review if not already
      there") and renumbered.
    - Added two new See-also follow-ups: T-NEW-a (plumb
      `CLOGLOG_PROJECT_ROOT` from launch) and T-NEW-b (relax
      `services.py:237` predecessor-resolution for `skip_pr` predecessors).
    - Added two new "Callers to audit" items for the plan-task framings and
      the legacy send-to-another-agent example.
14. Re-ran demo (had to `rm demo.md` first since `showboat init` refuses to
    overwrite). Quality re-ran clean: 557 passed + 1 xfailed (unrelated
    pre-existing), contract compliant, demo verified.
15. Committed, pushed, posted a summary reply as an issue comment on PR
    #152, moved task back to `review`.
16. PR #152 merged. Ran Section 2 shutdown sequence: `mark_pr_merged`,
    `report_artifact` (`docs/design/agent-lifecycle.md`), this work log and
    learnings file, then inbox echo + `unregister_agent`.

## Deliverables

- `docs/design/agent-lifecycle.md` — 404 lines across six required sections
  plus See-also and Callers-to-audit blocks. This is the artifact.
- `docs/demos/wt-f48-spec/demo-script.sh`,
  `docs/demos/wt-f48-spec/demo.md` — Showboat structural proof.
- PR #152 — merged.
- Task notes on T-222 capturing the review-exchange reasoning.

## Follow-ups the main agent should schedule

- **T-NEW-a** — launch skill exports `CLOGLOG_PROJECT_ROOT` so worktree
  agents stop rederiving the path.
- **T-NEW-b** — relax `src/agent/services.py:237` so `review`-status
  spec/plan predecessors are "resolved" when `artifact_path` is set,
  regardless of `pr_url`.

Plus the audit-pass items already in the See-also block: T-216 (docs
sync), T-220 (reconcile/close-wave rewrite), T-243 (`agent_unregistered`
event enforcement).
