# Wave wt-t323 — F-53 Plugin Portability Phase 3.10

**Date:** 2026-04-28
**Worktrees:** wt-t323-portability-pin-tests
**Feature:** F-53 Plugin Portability — Implementation

## Worktree summary

| Worktree | PR | Shutdown path |
|----------|-----|----------------|
| wt-t323-portability-pin-tests | [#263](https://github.com/sachinkundu/cloglog/pull/263) | cooperative |

## What shipped

**T-323 — Phase 3.10: pin tests — fresh-repo init smoke + plugin regression grep** ([PR #263](https://github.com/sachinkundu/cloglog/pull/263))

- Extended `tests/plugins/test_init_on_fresh_repo.py`:
  - `test_step3_settings_carries_no_host_specific_literals` — runs init Step 3 in a tmp repo and asserts `.claude/settings.json` carries no cloglog operator-host literal (`cloglog.voxdez.com`, `cloglog-webhooks`, `cloglog-dashboard-dev`, `../cloglog-prod`, reviewer-bot logins, `/home/sachin`); verifies brand surface (`cloglog`, `mcp-server/dist/index.js`) is preserved.
  - `test_step4a_config_yaml_carries_no_host_specific_literals` — same pin against post-Step-4a `.cloglog/config.yaml`.
- New `tests/plugins/test_plugin_no_cloglog_citations.py`:
  - 5 `test_no_global_host_literal[…]` cases pin global absence across `plugins/cloglog/`.
  - 2 `test_no_reviewer_bot_login_outside_design_docs[…]` cases extend T-316's per-file scope to all of `plugins/cloglog/` while exempting four cloglog-architecture files (`docs/two-stage-pr-review.md`, `docs/setup-credentials.md`, `docs/agent-lifecycle.md`, `skills/init/SKILL.md`).
  - `test_brand_surface_intact_in_plugin_tree` locks in the carve-out so a future widened sweep can't strip `cloglog` / `mcp__cloglog__` / `~/.cloglog/credentials`.
- Boy-scout: replaced two `/home/sachin/code/cloglog…` examples in `plugins/cloglog/docs/agent-lifecycle.md` with generic placeholders so the new global pin can stay strict.

### Codex review
- **Round 1 — `:pass:`**. Auto-merge gate held on `ci_not_green` initially; PR merged at 2026-04-28T15:38:32Z after CI flipped green — but only after operator nudge (filed as T-342: auto-merge gate's `ci_not_green` path stalls without re-trigger).

### Decisions captured in the per-task log
- **Source-tree line citations** (e.g. `src/agent/services.py:357-370`) are NOT pinned in this PR. Too many remain across plugin skill files and design docs; cleanup is out of scope for Phase 3 (pin tests). Filed implicitly for a future cleanup phase.
- **Brand surface carve-out** dropped `cloglog-mcp` from the brand-survives assertion — the MCP server name lives in `mcp-server/src/`, outside `plugins/cloglog/`, so it's out of scope for this sweep.
- **Reviewer-bot exemption** is a documented allowlist (`_REVIEWER_BOT_DOC_EXEMPT`), not a regex carve-out — a new doc that legitimately needs to name the bot must be added to the list with a comment, which is the right friction.

## Shutdown summary

- **wt-t323-portability-pin-tests** — cooperative shutdown. `agent_unregistered` with `tasks_completed: ["T-323"]`, `prs: {"T-323": "#263"}`, `reason: "pr_merged"`. Worktree, branches, and zellij tab removed cleanly.

## Learnings & issues

- **The pin-tests SKILL pattern resists scope creep.** The tempting move was to also pin source-tree line citations across `plugins/cloglog/`. T-323 deliberately deferred that — too many citations remain across skill files and design docs, and a strict pin would have blocked every PR until they're cleaned up. Phase 3 is *pin* tests for portability; *clean* tests are a separate scoped task.
- **Brand-surface carve-outs need exemption-list discipline, not regex carve-outs.** Adding `_REVIEWER_BOT_DOC_EXEMPT` as a fail-loud allowlist (rather than baking the four exempt paths into a regex) makes the next legitimate doc that needs to name the bot enter through an explicit code review, not through silent regex looseness.
- **Auto-merge stalled on `ci_not_green`** even though codex passed. Filed T-342 as a structural fix.

## Residual TODOs / heads-up for T-324

- T-324 needs the CI workflow to invoke `tests/plugins/test_init_on_fresh_repo.py` and `tests/plugins/test_plugin_no_cloglog_citations.py` directly — these are the two pin files this wave landed.
- The `_REVIEWER_BOT_DOC_EXEMPT` allowlist is a good place to grep when adding any new plugin doc that names a reviewer bot.

## State after this wave

- F-53 Phase 3.10 closed. Plugin regression grep + fresh-repo init smoke pinned.
- F-53 backlog: T-324 (Phase 3.11 CI wiring) — in flight, just launched.
- F-53 will be **complete** when T-324 lands.

## Test report

- **Quality gate:** `make quality` PASSED on this branch.
- **What was tested:** integration of T-323 against post-merge `main`; the new pin tests exercise both init's Step 3 settings.json output and the global plugin-tree absence checks.
- **Strategy:** verified cooperative shutdown left no zombie state, MCP tool surface unchanged.
