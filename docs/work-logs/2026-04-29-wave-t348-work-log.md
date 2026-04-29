# Wave t348 — work log

**Date:** 2026-04-29
**Wave:** wave-t348
**Worktrees in scope:** `wt-t348-bot-creds-env`

## Shutdown summary

| Worktree | PR | Shutdown path | Notes |
|----------|-----|---------------|-------|
| `wt-t348-bot-creds-env` | [#271](https://github.com/sachinkundu/cloglog/pull/271) | cooperative + manual tab close | Launcher PIDs 775385/775389 lingered after `unregister_agent` — reproduces T-352. |

## What shipped (T-348)

— *Inlined from `wt-t348-bot-creds-env/shutdown-artifacts/work-log.md`* —

GitHub-App bot identifiers (`GH_APP_ID` / `GH_APP_INSTALLATION_ID`) are now resolved by `plugins/cloglog/scripts/gh-app-token.py` itself in this order:

1. Process env (preserves operator overrides).
2. `.cloglog/local.yaml` (gitignored, host-local — preferred).
3. `.cloglog/config.yaml` (tracked fallback for single-operator repos).

The launch SKILL heredoc mirrors the same precedence and exports both variables into worktree-agent shells before invoking `claude`, so downstream `gh` calls that read `$GH_APP_ID` directly keep working across `/clear` (T-329).

`.cloglog/local.yaml` is added to `.gitignore`. The init SKILL's Step 8 was rewritten to gitignore `.cloglog/local.yaml` alongside `.cloglog/inbox` and to stage tracked config files explicitly — never `git add .cloglog/` as a directory — so a freshly-initialised consumer repo can never commit operator-specific identifiers.

`scripts/preflight.sh`, init/github-bot SKILL.md, both `setup-credentials.md` files, README.md, and CLAUDE.md were realigned on the new flow.

### Pin tests added (8)

Module: `tests/plugins/test_launch_skill_exports_gh_app_env.py`.

1. `test_launch_skill_defines_scalar_yaml_helper` — `_read_scalar_yaml()` exists in launch.sh heredoc, uses grep+sed (no python YAML lib).
2. `test_launch_skill_readers_resolve_env_first_then_local_then_config` — env → local.yaml → config.yaml precedence.
3. `test_launch_sh_exports_both_gh_app_env_vars` — gated on non-empty so empty config doesn't clobber a shell-RC export.
4. `test_no_operator_host_literals_in_plugin_or_tracked_cloglog_dir` — operator literals absent from plugin and tracked `.cloglog/`.
5. `test_config_yaml_does_not_carry_gh_app_keys` — direct inversion: tracked config.yaml MUST NOT carry the keys.
6. `test_local_yaml_is_gitignored`.
7. `test_init_step8_ignores_local_yaml_and_never_adds_cloglog_dir`.
8. `test_gh_app_token_script_resolves_from_local_yaml`.

Plus a fix to `tests/plugins/test_skills_use_plugin_root_scripts.py` so env-only pin tests run in `tempfile.TemporaryDirectory()` cwd (otherwise broken by an operator's populated `.cloglog/local.yaml`).

### Codex review (5/5 cap reached, 5 rounds, all caught real bugs)

| Round | Severity | Finding | Fix |
| --- | --- | --- | --- |
| 1 | MEDIUM | Top-level `README.md` + `docs/setup-credentials.md` left on old env-only contract | aligned to new flow (`ba04662`) |
| 2 | HIGH | init Step 6c silently skipped repo-access check on a fresh T-348 host | read config + forward env into subprocess (`8c44f44`) |
| 3 | 2× MEDIUM | (a) close-wave/reconcile/init/github-bot still required env-priming; (b) operator-host App IDs were tracked in config.yaml | central script-internal resolution + `.cloglog/local.yaml` gitignored host-local home (`899eddf`) |
| 4 | MEDIUM + HIGH | (a) env-only pin tests broken by populated `local.yaml`; (b) PEM paths pointed to wrong reviewer | smoke tests run in temp cwd; PEM paths corrected (`1461e71`) |
| 5 | MEDIUM + HIGH | (a) launch.sh readers didn't honor env-first precedence; (b) init Step 8 wholesale-staged `.cloglog/` | env early-return added to readers; explicit per-file staging (`6e530ed`) |

Operator merged after round-5 fixes (5/5 cap reached).

## Learnings & Issues

Folded into project CLAUDE.md (under `### Worktree env propagation`):

- **`/clear` between tasks ⇒ shell env any agent skill needs at runtime must be re-exported by `launch.sh`, NOT inherited from the operator's launching shell.** Generalises beyond `GH_APP` — any future runtime env var should land in `.cloglog/{local,config}.yaml` + the `launch.sh` heredoc, never in shell RC.
- **Operator-host bot identifiers must live in a gitignored file, not a tracked one.** `.cloglog/config.yaml` remains a fallback for single-operator repos, but the per-host home is `.cloglog/local.yaml`. Same constraint applies to any future per-operator value.

### Wave-level integration issues

- **Launcher PIDs lingered after `unregister_agent`** (PIDs 775385/775389). Same symptom as wt-t346. T-352 is now reproducible — promote priority on next pass.
- **Codex's 5/5 cap was reached but every round caught a real issue.** The fix architecture evolved substantially across rounds — final design (script-internal resolution + gitignored local.yaml + env-first precedence everywhere) is significantly better than the original AGENT_PROMPT plan. Lesson for future env-propagation: think about *every* caller of the credential before designing the fix, not just the worktree-agent path.

### Residual TODOs flagged by the agent

- Pre-existing operator literals at `docs/contracts/webhook-pipeline-spec.md:726-727` and `docs/work-logs/2026-04-28-wave-t322-work-log.md:46` are intentionally scope-narrowed pin skips — historical fixtures, separate cleanup task.
- `gh-app-token.py`'s new `_project_root()` probe shells out to `git rev-parse --show-toplevel`. CI image without git would fall back to env-only — not currently exercised.
- `.cloglog/local.yaml` is documented in prose only. Init does NOT auto-create it; operators must hand-create after step 6b. Onboarding friction risk — possible follow-up: init enhancement that prompts and writes `local.yaml`.
- launch.sh export of the two vars is now redundant for `gh-app-token.py` itself (the script resolves config independently) but still load-bearing for any downstream `gh`/`curl` call inside an agent that reads `$GH_APP_ID`. Leave the export in.

## State after this wave

- T-348 implementation merged: bot credentials no longer require shell-RC export; survive `/clear` and travel cleanly to consumer repos.
- MCP server tool surface unchanged this wave (sync-mcp-dist no-op).
- T-350 worktree agent still running; PR #273 in review.
- T-352 (launcher-lingering) re-confirmed, two reproductions on file.
