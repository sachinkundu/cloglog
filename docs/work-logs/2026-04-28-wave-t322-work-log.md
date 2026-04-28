# Wave wt-t322 — F-53 Plugin Portability Phase 2.9

**Date:** 2026-04-28
**Worktrees:** wt-t322-init-on-create-audit
**Feature:** F-53 Plugin Portability — Implementation

## Worktree summary

| Worktree | PR | Shutdown path | Commits | Files |
|----------|-----|----------------|---------|-------|
| wt-t322-init-on-create-audit | [#254](https://github.com/sachinkundu/cloglog/pull/254) | cooperative | 1 squash | 2 |

## What shipped

**T-322 — Phase 2.9: audit init's on-worktree-create.sh generation against design contract** ([PR #254](https://github.com/sachinkundu/cloglog/pull/254), merged a929ca4)

From `shutdown-artifacts/work-log-T-322.md`:

- `plugins/cloglog/skills/init/SKILL.md` Step 4b: widened the `on-worktree-create.sh` tech-stack matrix from 3 stacks (Python/uv, Node, Rust) to 8. Added Python without uv (pip/venv), Go (`go mod download`), Java/Maven (`mvn -B dependency:go-offline`), Java/Gradle (`./gradlew --no-daemon dependencies`), Ruby/Bundler (`bundle install`).
- Strengthened the unknown-stack stub: now includes the standard `set -euo pipefail` + `cd "${WORKTREE_PATH:?...}"` boilerplate so any commands a downstream operator adds run inside the new worktree (launch invokes the script by absolute path without changing cwd — finding from codex MEDIUM round 1).
- Added an explicit "Cloglog-specific extensions" callout in Step 4b that names `worktree-infra.sh`, `/api/v1/agents/close-off-task`, and `shutdown-artifacts/` reset as out-of-scope for init's generated script.
- New file: `tests/plugins/test_init_on_worktree_create.py` — 4 pin tests:
  1. `test_every_stack_block_is_nonempty` — every stack heading has a non-stub command body.
  2. `test_unknown_stack_stub_has_explanatory_comment` — unknown-stack stub references `WORKTREE_PATH`.
  3. `test_step4b_templates_have_no_cloglog_specific_commands` — no template leaks dogfood machinery.
  4. `test_step4b_documents_cloglog_extensions_as_out_of_scope` — Step 4b prose names the boundary.

### Quality gate
- `make quality` green: 1042 backend tests, 88.47% coverage, MCP tests, contract compliant, lint+types clean.
- Demo classifier auto-exempted as docs-only branch.

### Codex review
- Round 1 (1/5): MEDIUM finding — unknown-stack stub had no `cd "${WORKTREE_PATH...}"` boilerplate; addressed in bf13c1b.
- Round 2 (2/5): pass.
- Auto-merge gate returned `merge` after the codex pass.

## Shutdown summary

- **wt-t322-init-on-create-audit** — cooperative shutdown. Agent emitted `agent_unregistered` with `reason: "pr_merged"`, `tasks_completed: ["40ccf508-88c2-4d7b-b0e0-59758efd8e00"]`, `prs: {"T-322": "https://github.com/sachinkundu/cloglog/pull/254"}`. Worktree, local branch, remote branch, and zellij tab removed cleanly.

## Learnings & issues

- **Auto-merge gate is invoked manually on the codex-pass `review_submitted` inbox event.** The github-bot skill's "PR Event Inbox" handler closes the loop; without running the gate the PR sits MERGEABLE/CLEAN with `autoMergeRequest: null` indefinitely. (Already documented in CLAUDE.md "Auto-merge / PR gates" — reaffirmed by this wave.)
- **Unknown-stack template needs the `cd` boilerplate.** Even when the body is "operator fills this in later", the boilerplate must match the other stacks because `launch.sh` runs the bootstrap script by absolute path without changing cwd. Codex caught this in round 1.
- **Audit deliverable lists are deliberately under-specified.** The audit doc said "Go? Java/Maven? Python without uv?" — the right move was to grep the audit's own evidence trail and ship the union of obvious gaps in one round, since codex's 5/5 cap is unforgiving on factual-precision PRs.
- **`gh-app-token.py` requires `GH_APP_ID` and `GH_APP_INSTALLATION_ID` env vars set in the shell.** Not auto-loaded from `.env` (per existing CLAUDE.md learning). Operator export: `export GH_APP_ID=3235173 GH_APP_INSTALLATION_ID=120404294`.
- **`zellij action go-to-tab-by-name` is wrong; the correct subcommand is `go-to-tab-name`.** Affects the relaunch / tab-switch snippets in `plugins/cloglog/skills/launch/SKILL.md:185` and `plugins/cloglog/skills/setup/SKILL.md:110`. close-wave does not use this subcommand, but it still has a separate Step 5c tab-closing bug (bare `close-tab` with no `--tab-id`, which closes the focused tab — i.e. the supervisor's own) tracked in T-339. Follow-ups: (1) replace `go-to-tab-by-name` with `go-to-tab-name` in launch and setup; (2) fix close-wave Step 5c to use `list-tabs` + `close-tab --tab-id` per `docs/zellij-guide.md:12-27` (T-339).

## State after this wave

- F-53 phase 2.9 (init Step 4b audit) shipped. Init now generates `on-worktree-create.sh` for 8 tech stacks with consistent boilerplate; cloglog-specific extensions explicitly out-of-scope.
- F-53 backlog remaining: T-316 (in flight, PR #255), T-319 (in flight), T-321, T-323, T-324.

## Test report

- **Quality gate on close-wave branch:** see commit — runs `make quality` before PR push.
- **What was tested:** integration of T-322's merged changes against current `main`; pin tests in `tests/plugins/test_init_on_worktree_create.py` execute against the merged init SKILL.md.
- **Strategy:** verify origin/main fast-forward merge clean, run quality gate to catch any post-merge integration drift, confirm cooperative shutdown left no zombie state.
