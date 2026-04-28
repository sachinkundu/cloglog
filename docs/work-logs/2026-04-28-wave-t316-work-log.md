# Wave wt-t316 — F-53 Plugin Portability Phase 1.3

**Date:** 2026-04-28
**Worktrees:** wt-t316-config-yaml-keys
**Feature:** F-53 Plugin Portability — Implementation

## Worktree summary

| Worktree | PR | Shutdown path | Commits | Files |
|----------|-----|----------------|---------|-------|
| wt-t316-config-yaml-keys | [#255](https://github.com/sachinkundu/cloglog/pull/255) | cooperative | 1 squash | 15 |

## What shipped

**T-316 — Phase 1.3: replace literal hardcoded values with `.cloglog/config.yaml` keys** ([PR #255](https://github.com/sachinkundu/cloglog/pull/255), merged 6517476)

From `shutdown-artifacts/work-log.md`:

- New config keys in `.cloglog/config.yaml`: `reviewer_bot_logins`, `dashboard_key`, `webhook_tunnel_name`, `demo_allowlist_paths`. `prod_worktree_path` was already in config; close-wave prose now references it instead of literal `../cloglog-prod`.
- `plugins/cloglog/scripts/auto_merge_gate.py` retired the `CODEX_BOT_LOGIN` constant; `GateInputs` grew a `reviewer_bot_logins` field; the gate walks up from CWD to read the list from config when the JSON payload omits it. Stdlib-only YAML mini-parser added (`_parse_top_level_list`, `_find_config_yaml`) — necessary because the gate runs under system `python3` (no PyYAML).
- `scripts/check-demo.sh` and `plugins/cloglog/skills/demo/SKILL.md` share a single grep+sed reader for `demo_allowlist_paths` (single YAML scalar regex). Eliminates the previous "must be kept bit-identical" coupling.
- `scripts/preflight.sh` reads `webhook_tunnel_name` via canonical `read_yaml_scalar`; cloudflared-not-running error suggests `cloudflared tunnel run $webhook_tunnel_name`.
- Skill prose in `github-bot`, `launch`, `close-wave`, `demo`, and `init` references config keys instead of literal strings.
- `init/SKILL.md` Step 4a updated to document all four new T-316 keys with sensible defaults (codex round 1 finding — fresh init was emitting incomplete config).

### Codex review rounds

- **Round 1** flagged two issues:
  - **HIGH** — `scripts/preflight.sh` raw `grep | head | sed | sed | tr` pipeline aborted under `set -euo pipefail` when `webhook_tunnel_name` absent. Switched to `read_yaml_scalar`.
  - **MEDIUM** — `plugins/cloglog/skills/init/SKILL.md` Step 4a didn't document the new T-316 keys. A fresh init would emit a config missing every key, breaking the demo gate and auto-merge flow on day one. Added all four keys with defaults; pinned by `tests/plugins/test_init_bootstrap_skill.py::test_step4a_documents_t316_config_keys`.
- **Round 2** flagged one issue:
  - **MEDIUM** — Initial config listed both reviewer bots in `reviewer_bot_logins`. Auto-merge gate accepts any login from that list, so an opencode stage-A approval could merge a PR before codex stage B runs — violating `${CLAUDE_PLUGIN_ROOT}/docs/two-stage-pr-review.md`. Removed opencode; `reviewer_bot_logins` is the auto-merge-eligible *final-stage* set. Pinned by `test_reviewer_bot_logins_excludes_stage_a_opencode`.
- **CI fix** — `tests/plugins/test_plugin_docs_self_contained.py::test_no_hardcoded_plugin_repo_path_in_plugin_sources` rejected the round-2 prose pointer (`plugins/cloglog/docs/two-stage-pr-review.md`); plugin sources must reference docs via `${CLAUDE_PLUGIN_ROOT}/docs/`.
- **Round 3** — `:pass:`. Auto-merge gate held once on `ci_not_green`, waited synchronously via `gh pr checks --watch`, re-evaluated, gate returned `merge`, PR squash-merged.

### Tests added or extended

- `tests/plugins/test_t316_no_hardcoded_literals.py` *(new)* — 5 absence-pins (per literal × per affected file), 1 presence-pin, 1 stage-scope pin.
- `tests/test_auto_merge_gate.py` — retired `gate.CODEX_BOT_LOGIN` for `_TEST_REVIEWER`; added cases for production invocation shape (config walk-up + missing-config fallback).
- `tests/test_check_demo_allowlist.py` — fixture provisions `.cloglog/config.yaml` in `tmp_path`; added `test_missing_config_yaml_errors_loudly` and `test_config_driven_allowlist_picks_up_overrides`.
- `tests/test_check_demo_exemption_hash.py` — fixture provisions config alongside existing diff_hash pins.
- `tests/plugins/test_init_bootstrap_skill.py` — new `test_step4a_documents_t316_config_keys`.

## Shutdown summary

- **wt-t316-config-yaml-keys** — cooperative shutdown. Agent emitted `agent_unregistered` with `reason: "pr_merged"`, `tasks_completed: ["159b4784-2b4c-4374-b748-048a011d81ec"]`, `prs: {"T-316": "https://github.com/sachinkundu/cloglog/pull/255"}`. Worktree, local branch, remote branch, and zellij tab removed cleanly.

## Learnings & issues

- **`auto_merge_gate.py` is NOT in the demo allowlist.** Any PR that touches `plugins/cloglog/scripts/auto_merge_gate.py` requires an exemption or real demo (allowlist is `plugins/[^/]+/(hooks|skills|agents|templates)/`). If a future task expands the allowlist to cover `plugins/*/scripts/`, drop a line in the demo skill prose noting the rationale.
- **`demo_allowlist_paths` is a single YAML scalar regex, not a list.** Pragmatic choice to keep the existing `read_yaml_scalar` helper viable. If a future operator wants per-line audit-friendly allowlist edits, factor a `read_yaml_list` helper into `plugins/cloglog/hooks/lib/parse-yaml-scalar.sh` first.
- **Skill prose now points to `${CLAUDE_PLUGIN_ROOT}/docs/two-stage-pr-review.md`** (not repo-relative). The `test_no_hardcoded_plugin_repo_path_in_plugin_sources` pin enforces this — the repo-relative path only resolves in the cloglog dogfood checkout. Audit any new prose pointer added to a skill against this rule before pushing.
- **`CODEX_BOT_LOGIN` retirement was clean** — only `tests/test_auto_merge_gate.py` consumed it as a library import. Re-grep before retiring any other module-level identity constant.

## State after this wave

- F-53 Phase 1.3 shipped. Cloglog-specific strings (`reviewer_bot_logins`, `dashboard_key`, `webhook_tunnel_name`, `demo_allowlist_paths`, `prod_worktree_path`) all live in `.cloglog/config.yaml`; downstream projects can override without forking the plugin.
- F-53 backlog remaining: T-319 (in flight, init placeholder resolution), T-321 (deferred — touches init/SKILL.md, sequential after T-319), T-323 (pin tests, depends on impl), T-324 (CI wiring, depends on T-323).
- **Heads-up for T-319**: T-316 also modified `init/SKILL.md` Step 4a (added the four new config keys). T-319's branch was created from origin/main before T-316 merged — expect a rebase on `init/SKILL.md` when T-319 opens its PR.

## Test report

- **Quality gate:** `make quality` PASSED on this branch (run before PR push).
- **What was tested:** integration of T-316's merged changes against current `main`; pin tests in `tests/plugins/test_t316_no_hardcoded_literals.py`, `test_auto_merge_gate.py`, `test_check_demo_allowlist.py`, `test_check_demo_exemption_hash.py`, and `test_init_bootstrap_skill.py` exercise the new config-key plumbing.
- **Strategy:** verified cooperative shutdown left no zombie state, confirmed no integration drift after fast-forward of `origin/main` (T-322 and T-316 merged sequentially without conflict), checked MCP tool surface unchanged so no broadcast needed.
