# Wave wt-t324 — F-53 Plugin Portability Phase 3.11 (final wave)

**Date:** 2026-04-28
**Worktrees:** wt-t324-init-smoke-ci
**Feature:** F-53 Plugin Portability — Implementation
**Status:** F-53 **COMPLETE** with this wave.

## Worktree summary

| Worktree | PR | Shutdown path |
|----------|-----|----------------|
| wt-t324-init-smoke-ci | [#265](https://github.com/sachinkundu/cloglog/pull/265) | cooperative |

## What shipped

**T-324 — Phase 3.11: wire fresh-repo init smoke into CI** ([PR #265](https://github.com/sachinkundu/cloglog/pull/265))

Plugin portability gate as a CI workflow. `.github/workflows/init-smoke.yml` runs the T-319/T-321/T-323 fresh-repo init pin tests on every PR (no `paths:` filter), so a portability regression in plugin SKILL.md, hooks, docs, or settings is merge-blocking on every downstream change.

### Files
- `.github/workflows/init-smoke.yml` *(new, 60 lines)* — smoke job with Postgres service.
- `.github/workflows/ci.yml` *(+1)* — `init-smoke.yml` added to `pull_request.paths` so edits to the smoke workflow trigger the main test suite.
- `tests/plugins/test_init_smoke_ci_workflow.py` *(new, 5 tests)* — both test-file references present, `pull_request` trigger declared, no `paths:` filter on the smoke workflow itself, and `ci.yml` includes `init-smoke.yml` in its paths.
- `CLAUDE.md` *(+10)* — new `## CI` section documenting both workflows.

### Codex review
| Round | Finding | Resolution |
|-------|---------|------------|
| codex 1/5 (MEDIUM) | smoke job has no Postgres service; `tests/conftest.py`'s session-autouse fixture fails before any assertion runs | `services.postgres` block in `e2851cb` (matches `ci.yml`'s shape) |
| codex 2/5 (MEDIUM) | `ci.yml`'s `paths:` doesn't match `init-smoke.yml`, so a self-disabling rewrite of the smoke workflow could merge with no CI at all | added `init-smoke.yml` to `ci.yml`'s `paths:`, pinned by `test_main_ci_runs_on_init_smoke_workflow_changes` in commit `151d52b` |
| codex 2/5 re-review | `:pass:` | auto-merged |

## Shutdown summary

- **wt-t324-init-smoke-ci** — cooperative shutdown. `agent_unregistered` with `tasks_completed: ["T-324"]`, `prs: {"T-324": "#265"}`, `reason: "pr_merged"`. Worktree, branches, and zellij tab removed cleanly.

## Learnings & issues

- **Any new pytest-driven CI job inherits `tests/conftest.py`'s session-autouse Postgres fixture.** It is unconditional — even pure static-file pin tests in `tests/plugins/` trigger it because pytest loads `conftest.py` at collection time. Two options for new jobs: (1) attach a Postgres service matching `ci.yml`'s shape, or (2) invoke pytest with `--noconftest` (untested in this repo; would also disable any plugin-specific conftest config). Option (1) is the safer default. **Folding into CLAUDE.md** under the CI section.
- **A workflow guarded only by its own pin tests is not self-protecting if the same PR can disable both.** The smoke workflow had a `paths`-filter pin, but if that pin lives only in the workflow it tests, a PR editing the workflow to skip itself never runs the pin. The defence is cross-coverage: pin the smoke workflow's shape AND make a *different* workflow (one whose `paths` cannot be edited away in the same PR) responsible for executing the pin file. **Generalises beyond CI** — any "guard X with pin test Y" arrangement has to ensure Y is reachable on the diff that breaks X. Codex round 2 caught this; the cross-coverage assertion landed in `151d52b`.

## State after this wave — F-53 COMPLETE

All six F-53 implementation tasks shipped:

| Task | Phase | PR |
|------|-------|----|
| T-322 | 2.9 — init Step 4b tech-stack matrix audit | #254 |
| T-316 | 1.3 — hoist literals into `.cloglog/config.yaml` | #255 |
| T-319 | 2.6 — resolve init placeholders at runtime | #257 |
| T-321 | 2.8 — generate `project_id` + commented `worktree_scopes` at init | #260 |
| T-323 | 3.10 — pin tests: fresh-repo init smoke + plugin regression grep | #263 |
| T-324 | 3.11 — wire fresh-repo init smoke into CI | #265 |

Plus T-231 (`gunicorn --capture-output`, PR #261) — diagnostic side-quest filed during the F-53 dance.

Filed for follow-up:
- **T-340** — MCP retrigger-codex tool (workaround for codex re-trigger drops).
- **T-341** — Bug: review_engine silently drops codex re-trigger on synchronize for some PRs.
- **T-342** — Bug: auto-merge gate's `ci_not_green` path stalls without re-trigger.

The cloglog plugin is now portable: a downstream project running `/cloglog init` against a fresh repo gets a working `.cloglog/config.yaml` with `project_id`, a commented `worktree_scopes` template, and resolved-at-init paths in `.claude/settings.json`. Pin tests + CI smoke gate every change.

## Test report

- **Quality gate:** `make quality` PASSED on this branch.
- **What was tested:** integration of T-324 against post-merge `main`; both new pin tests `test_init_smoke_ci_workflow.py` (5 tests) execute against the new workflow file. The `init-smoke.yml` job ran on PR #265 itself and on every PR after.
- **Strategy:** verified cooperative shutdown left no zombie state, MCP tool surface unchanged.
