# Wave wt-t319 — F-53 Plugin Portability Phase 2.6

**Date:** 2026-04-28
**Worktrees:** wt-t319-init-placeholders
**Feature:** F-53 Plugin Portability — Implementation

## Worktree summary

| Worktree | PR | Shutdown path | Commits | Files |
|----------|-----|----------------|---------|-------|
| wt-t319-init-placeholders | [#257](https://github.com/sachinkundu/cloglog/pull/257) | cooperative | 1 squash | 2 |

## What shipped

**T-319 — Phase 2.6: resolve init placeholders at runtime** ([PR #257](https://github.com/sachinkundu/cloglog/pull/257), merged before this close-wave)

`/cloglog init` Steps 3 and 7a now resolve placeholder paths at runtime instead of writing literal `<...>` markers into operator settings files.

- Step 3 was a JSON example block embedding `<absolute-path-to-project>` and `/path/to/mcp-server/dist/index.js`. It is now an executable bash block that resolves `PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT}"`, computes absolute paths to `hooks/session-bootstrap.sh` and `mcp-server/dist/index.js`, prompts when the bundled mcp-server build is missing, and merges the result into `.claude/settings.json` via an idempotent Python heredoc.
- Step 7a swaps `PLUGIN_ROOT="<path to plugins/cloglog>"` for `PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT}"`.
- `tests/plugins/test_init_on_fresh_repo.py` *(new)* — 4 pin tests covering both the prose (no literal placeholders survive) and the behaviour (Step 3 block, executed against a synthesised plugin tree in `tmp_path`, produces `settings.json` with absolute resolved paths and the supplied backend URL).

### Codex review
- `:pass:` on first session — no findings to address. Auto-merge gate held on `ci_not_green` once, watched checks to green, re-evaluated and merged.

## Shutdown summary

- **wt-t319-init-placeholders** — cooperative shutdown. Agent emitted `agent_unregistered` with `reason: "pr_merged"`, `tasks_completed: ["c492295b-555e-4a04-a66e-3673f57f4eae"]`, `prs: {"T-319": "https://github.com/sachinkundu/cloglog/pull/257"}`. Worktree, local branch, remote branch, and zellij tab removed cleanly.

## Learnings & issues

- **Resolved bootstrap path is written into `settings.json` verbatim**, not via `${CLAUDE_PLUGIN_ROOT}`. SessionStart hooks do not expand `${CLAUDE_PLUGIN_ROOT}`, so the absolute path is mandatory. The Python heredoc reads the live value at init time and writes the resulting absolute string.
- **Missing mcp-server build prompts** rather than writing `/path/to/mcp-server/dist/index.js`. Operator-side resolution is preferred over a literal placeholder that the gate would never catch.
- **Test extracts the bash block at runtime** (regex on the SKILL.md) rather than duplicating the script body — drift between the documented block and the tested block is impossible.
- **Worktree `.cloglog/config.yaml` may not include `reviewer_bot_logins`.** The auto-merge gate's CWD-walk-up finds the worktree's config first, not the main repo's. When invoking the gate manually from a worktree, pass `reviewer_bot_logins` inline in the JSON payload, or add the key to the worktree config — otherwise the gate exits `not_codex_reviewer` even when the inbox event clearly came from `cloglog-codex-reviewer[bot]`. This is the post-T-316 reality and is worth a CLAUDE.md callout.
- **`CLAUDE_PLUGIN_ROOT` is set at init time, not at SessionStart hook invocation time.** That is why init's job is to *resolve* it once and bake the absolute path into `.claude/settings.json` — the SessionStart machinery later does not get a second chance.

## Residual TODOs / heads-up for next phase (T-321, T-323, T-324)

- The audit doc's Phase 2 step 6 brief said `tests/plugin/` (singular); the actual landing path is `tests/plugins/`. Update the audit doc if any later phase quotes that path.
- Phase 3.10 (T-323) of the audit will extend `tests/plugins/test_init_on_fresh_repo.py` with cross-stack fresh-repo smoke assertions (no `cloglog-prod`, no hardcoded reviewer logins, no `/home/sachin/...`). The current 4 tests are scoped to Step 3/7a placeholders only — leave room for those additional cases in the same file.
- The `/cloglog init` flow still emits `claude plugins install /path/to/plugins/cloglog` in its prerequisites (line 26). That is prose, not an executable block, so it falls outside T-319's scope, but the same placeholder-resolution discipline will need to cover it when init is next exercised against a marketplace-installed plugin tree.

## State after this wave

- F-53 Phase 2.6 shipped. Init no longer writes literal `<...>` placeholders into operator settings — Steps 3 and 7a resolve `${CLAUDE_PLUGIN_ROOT}`-based paths at init time.
- F-53 backlog remaining: T-321 (in flight, Phase 2.8 — generate `worktree_scopes` + `project_id` at init time), T-323 (Phase 3.10 pin tests, depends on T-321), T-324 (Phase 3.11 CI wiring, depends on T-323).

## Test report

- **Quality gate:** `make quality` PASSED on this branch (run before PR push).
- **What was tested:** integration of T-319 against post-merge `main` (which now also includes T-316 and T-322); the new `test_init_on_fresh_repo.py` exercises the live Step 3 block against a synthesised plugin tree.
- **Strategy:** verified cooperative shutdown left no zombie state, MCP tool surface unchanged so no broadcast needed.
