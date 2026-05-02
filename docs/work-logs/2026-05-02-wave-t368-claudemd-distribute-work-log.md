# Worktree work log — wt-t368-claudemd-distribute

Closed cleanly after T-368 PR merged. Aggregated from per-task work logs
in chronological order.

---
## T-368 — Distribute CLAUDE.md Agent Learnings to proper homes

**Feature:** F-44 (Documentation & Design Doc Maintenance)
**PR:** https://github.com/sachinkundu/cloglog/pull/284 (merged)
**Worktree:** `wt-t368-claudemd-distribute`

### What shipped

CLAUDE.md trimmed from 241 → 99 lines by removing the session-by-session
"Agent Learnings" dump and routing each learning to its proper home per
the disposition table agreed at launch.

Final commit chain (5 rounds with codex):

1. `7ecbc73` — initial distribution: deleted `## Agent Learnings`,
   appended new sections to `docs/invariants.md`, `launch/SKILL.md`,
   `demo/SKILL.md`, `github-bot/SKILL.md`, `close-wave/SKILL.md`,
   `prod-branch-tracking.md`.
2. `393ec4d` — codex round 1 [MEDIUM]: routed close-wave Step 11/13 and
   pr-postprocessor agent away from hardcoded `CLAUDE.md` to a
   destination-by-home table.
3. `50ec483` — codex round 2 [MEDIUM/HIGH/CRITICAL]: extended `make
   invariants` from 12 → 27 pin nodes (now 86 tests vs prior 61);
   fixed `ddd-context-map.md` path; updated reconcile SKILL.
4. `6d14859` — codex round 3 [HIGH] + CI fix: rewrote
   prod-branch-tracking.md §4.1 / §5.1 / §10 (T-prod-2) to
   publish-pointer-last; switched plugin design-doc examples to non-
   mirrored docs to satisfy `test_plugin_docs_self_contained.py`.
5. `2121a08` — codex round 4 [HIGH/CRITICAL/HIGH]: narrowed the
   notifications invariant to actual implementation; added
   `TestPostReview::` / `TestFullFlowIntegration::` class prefixes to
   review_engine pin nodeids in invariants.md; replaced
   `git add docs/work-logs/` with explicit-filename form.
6. `de6661a` — codex round 5 [HIGH/MEDIUM]: retired CLAUDE-only
   learnings flow in `worktree-agent.md` and
   `agent-lifecycle.md` §5.5; added the four launch/template pin
   modules to `init-smoke.yml` (always-on PR gate that survives
   ci.yml's `paths:` filter); pinned the new contract via
   `test_init_smoke_ci_workflow.py::test_workflow_runs_launch_and_template_pins`.

### Files touched

- `CLAUDE.md` (241 → 99 lines)
- `docs/invariants.md` (223 → ~370 lines; added Notifications, Review
  engine, EventBus, MCP server registration, Workflow templating
  sections — all reuse existing pins)
- `docs/design/prod-branch-tracking.md` (§4.2.1 added; §4.1, §5.1,
  T-prod-2 rewritten)
- `docs/design/agent-lifecycle.md` (§5.5 routing language)
- `plugins/cloglog/skills/launch/SKILL.md` (Gotchas section)
- `plugins/cloglog/skills/demo/SKILL.md` (Demo proof gotchas + classifier
  allowlist)
- `plugins/cloglog/skills/github-bot/SKILL.md` (Gotchas: merge vs rebase,
  ff-only pull, gh pr view shape, statusCheckRollup empty case, codex
  COMMENT vs CHANGES_REQUESTED)
- `plugins/cloglog/skills/close-wave/SKILL.md` (Step 11 routing table,
  Step 13 generalised, gh pr merge gotcha, pytest subprocess gotcha)
- `plugins/cloglog/skills/reconcile/SKILL.md` (Step 5.0 rationale)
- `plugins/cloglog/agents/pr-postprocessor.md` (Step 2 routing table,
  Step 5 explicit-path stage, frontmatter description)
- `plugins/cloglog/agents/worktree-agent.md` (postprocessor description)
- `Makefile` (`invariants` target: 12 → 27 pin nodes; runs 86 tests)
- `.github/workflows/init-smoke.yml` (added 4 launch/template pin
  modules)
- `tests/plugins/test_init_smoke_ci_workflow.py` (new pin
  `test_workflow_runs_launch_and_template_pins`)

### Quality gate

- `make invariants`: 86 passed (was 61 before this PR)
- `make quality`: full pass (lint, typecheck, 1166 backend tests,
  contract, MCP server, demo auto-exempt — docs-only allowlist)
- `tests/plugins/`: 227 passed, 1 skipped

### Decisions / non-obvious choices

- **No new pin tests added in this PR** per task constraint — reused
  existing pins for every new invariants entry. The constraint named a
  separate task to tighten invariants.md tier columns.
- **Drops vs invariants vs SKILL** boundary: silent-failure invariants
  (with a pin) → invariants.md; workflow gotchas → SKILL/template/agent;
  architectural decisions → design doc; one-off / meta → drop. The
  routing table now lives in close-wave Step 11 and the pr-postprocessor
  agent — replicated to two places intentionally so neither doc can
  drift in isolation.
- **Plugin self-containedness pin** forbids bare `docs/design/` references
  for the three docs mirrored into `${CLAUDE_PLUGIN_ROOT}/docs/`
  (agent-lifecycle, setup-credentials, two-stage-pr-review). Round-3
  attempt 1 listed two of those forbidden files in the design-doc
  routing examples; corrected on attempt 2 to use only
  prod-branch-tracking.md and ddd-context-map.md, with a "most live
  under docs/design/" shape.
- **`make invariants` extension was forced** by the round-2 codex
  finding that invariants.md said "Run the full set with `make
  invariants`" but the target ran only the older 12 nodes. Adding the 15
  new nodes to the recipe was the smaller fix vs. trimming the doc.
- **Two test nodeids needed correction** while doing the make-target
  extension: opencode-only test lives in `test_review_engine_t248.py`
  (not the main `test_review_engine.py`), and the commit_id pins live
  inside `TestPostReview` / `TestFullFlowIntegration` classes (the
  CLAUDE.md learning had cited unqualified test names).

### Mid-task self-correction

Initial Edit calls leaked into the main checkout via absolute paths that
bypassed the worktree prefix (the exact CLAUDE.md "Edit/Write file_path
inside a worktree must include the .claude/worktrees/<wt-name>/ prefix"
warning). Caught by side-by-side `wc -l` showing main had `invariants.md
= 363` while worktree had `223`. Fix: copied modified content into
worktree, `git restore`d main, re-verified by diffing both trees and
re-running invariants.

### Residual TODOs / context the next task should know

- **Follow-up task already named in `task.md`**: tighten
  `docs/invariants.md` header, add a tier column (text-pin /
  render-pin / behavioral-smoke), audit each entry against the
  tightened bar. The 15 entries this PR added are deliberately not
  yet annotated with tier metadata — that work belongs in the
  follow-up task. Some of the additions reuse pins that are
  text-presence pins (e.g. `test_skills_no_remote_set_url.py`) and
  some are behavioral (e.g. `test_event_bus_cross_worker.py`); the
  follow-up will normalise the bar.
- **CLAUDE.md backstop tests in the gateway test suite carry stale
  prose references** ("see CLAUDE.md ..." in docstrings of
  `test_review_engine.py` and
  `test_notification_listener_does_not_toast_on_review_transition.py`).
  These are docstring-only and don't fail any assertion; they're a
  cleanup target for the follow-up task or any future PR touching
  those files.
- **`docs/work-logs/` is the close-wave aggregation target**, but no
  new work-logs land via this PR (worktree close-wave is the wave
  closer, not this task). The `pr-postprocessor.md:114` updated stage
  example uses `git add "docs/work-logs/$(date +%Y-%m-%d)-<worktree_name>.md"`
  which is the right shape going forward.
- **Codex 5/5 cap was reached** on this PR. The bot's final comment was
  "Review skipped: this PR reached the maximum of 5 bot review sessions
  without the bot reaching approval. Request human review." All five
  codex findings rounds were addressed and pushed; the human merge
  signals approval despite no bot-side `event="APPROVED"` review.
