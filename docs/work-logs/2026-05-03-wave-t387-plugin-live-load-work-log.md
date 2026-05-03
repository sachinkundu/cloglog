# Wave: t387-plugin-live-load (2026-05-03)

Single-worktree, single-task wave: `wt-t387-plugin-live-load` shipped T-387 (PR #304). Bundled into the same PR as the wt-codex-review-fixes wave because the supervisor's one-active-task guard would otherwise have required waiting on T-389 to land before starting T-391.

## Worktree summary

| Worktree | Tasks | PRs | Shutdown path |
|----------|-------|-----|----------------|
| wt-t387-plugin-live-load | T-387 | #304 | cooperative (`agent_unregistered` at 10:12:18) |

---

## T-387 — Plugin cache freezes at install time — load plugin live via `claude --plugin-dir`

PR: https://github.com/sachinkundu/cloglog/pull/304 (codex stage B `:pass:` on session 1/5; auto-merge gate returned `merge`)

### Summary

Worktree agents previously loaded the cloglog plugin from `claude`'s install-time cache (populated by `claude plugins install`), so edits to `plugins/cloglog/skills/**`, `hooks/**`, or `templates/**` made in the dev worktree were silently invisible to subsequently spawned agents until the operator manually re-ran `claude plugins install --force`. Confirmed `claude --help` exposes `--plugin-dir <path>` ("Load plugins from a directory for this session only"). The rendered `launch.sh` now passes `--plugin-dir $WORKTREE_PATH/plugins/cloglog`, gated on `[[ -d ... ]]` so downstream projects without an in-tree plugin copy keep the existing behaviour.

### Files touched

- `plugins/cloglog/skills/launch/SKILL.md` — inside the quoted heredoc that renders `launch.sh`, added `_PLUGIN_DIR_FLAG` resolution and appended the flag to the `claude` invocation.
- `plugins/cloglog/skills/init/SKILL.md` — split prereq #1 into Mode A (`claude plugins install`, downstream) and Mode B (`claude --plugin-dir`, plugin development).
- `tests/plugins/test_launch_sh_loads_plugin_live.py` — new pin: 3 cases — flag present, anchored on `$WORKTREE_PATH/plugins/cloglog`, prose mentions `--plugin-dir` + `T-387`.
- `docs/invariants.md` — new entry under "Workflow templating" naming the silent-failure mode and pointing at the pin test.
- `Makefile` — `invariants` target now runs the new pin alongside `test_launch_skill_renders_clean_launch_sh.py`.

### Decisions / non-obvious bits (from the per-task work log)

- `--plugin-dir` is the spelling claude actually exposes (`-dir`, not `-dirs`). Verified via `claude --help`.
- Path is rooted on `$WORKTREE_PATH/plugins/cloglog` (each worktree's local plugin copy), NOT a shared `~/.claude/plugins/...` path. The whole point is per-worktree isolation: edits in branch X are invisible to a parallel agent in branch Y.
- The `[[ -d ... ]]` guard makes the flag opt-in. Downstream projects that don't vendor `plugins/cloglog/` in-tree are unaffected — Mode A (install-cache) still applies for them.
- Pin assertions are by **presence + anchoring + prose**. Anchoring is the load-bearing one: a regression that hardcodes `~/.claude/plugins/...` would still satisfy "flag present" but reopen the freeze. The prose pin ensures any future edit dropping the flag also has to remove the rationale, surfacing the breakage instead of silently shipping it.
- Existing `test_launch_skill_renders_clean_launch_sh.py` still passes — the new flag lives inside the quoted heredoc, doesn't introduce `\$N` escapes, and `bash -n` on the rendered file still passes.

### Codex review

Stage B (codex) `:pass:` on session 1/5. CI green (ci, init-smoke, e2e-browser). Auto-merge gate returned `merge`; PR squash-merged.

---

## Shutdown summary

| Step | Detail |
|------|--------|
| `agent_unregistered` arrived | 2026-05-03T10:12:18+03:00, `tasks_completed: [T-387]`, `prs: {T-387: #304}`, `reason: pr_merged` |
| Shutdown path | cooperative — per-task `work-log-T-387.md` was present and inlined into this wave log before worktree teardown |
| Surviving launcher | yes — same pattern as wt-codex-review-fixes (T-390). Closed via `close-zellij-tab.sh`; launcher trap fired on HUP. **Note:** because this worktree was launched BEFORE T-387 landed, it ran on the cache-frozen plugin — exactly the path T-387 fixed. The next post-T-387 worktree is the one that should test whether the surviving-launcher behaviour self-corrects. |
| Worktree on main | the agent's `gh pr merge --squash --delete-branch` left the worktree on `main` (not on `wt-t387-plugin-live-load`). `git worktree remove --force` handled this; no special action needed. |
| Worktree removed | `git worktree remove --force` ok; local + remote `wt-t387-plugin-live-load` already deleted by `gh pr merge --delete-branch` |
| `make sync-mcp-dist` | tool surface unchanged — no broadcast |

## Learnings & Issues

### Routing
- **Plugin live-load is now the default for in-tree-vendored plugins.** Documented in `docs/invariants.md` (added by the T-387 PR itself). No additional routing in this wave log.
- **Mode A vs Mode B in init SKILL.md** — also documented in PR #304's edits to `plugins/cloglog/skills/init/SKILL.md`. The wave doesn't add prose; the SKILL is the source of truth.
- **Worktrees launched pre-T-387 still run the install-cache path until they exit.** Operationally this only affects in-flight worktrees at the moment T-387 merged (wt-t388-db-isolation and wt-t382-per-project-creds were both launched off origin/main BEFORE T-387 landed — they're on the install-cache path, not the live-load path. Their next continuation relaunch (or a fresh launch after they finish) will pick up the live-load behaviour).

### Cross-task notes
- T-354 (drop SKILL-embedded heredoc entirely) is the long-term fix; T-387 is the minimal scope.
- T-382 (`wt-t382-per-project-creds`) was in flight on the same `launch.sh` heredoc when T-387 merged. T-382's PR will need to rebase off main and resolve the heredoc conflict; the post-render `sed -i` substitution lines are the fragile part.
- T-390 (surviving launcher) — see PR #305's shutdown summary for the open question.

## State after this wave

- Worktree agents launched after T-387's merge load `plugins/cloglog/**` live from each worktree's own copy via `claude --plugin-dir`.
- Edits to skills / hooks / templates in branch X are isolated from a parallel agent in branch Y, and visible to the next agent launched in branch X without manually re-running `claude plugins install --force`.
- Worktree `wt-t387-plugin-live-load` torn down clean (local + remote branches gone via `gh pr merge --delete-branch`, worktree removed, MCP dist rebuilt — surface unchanged).
- F-48 (Agent Lifecycle Hardening) backlog still has T-388, T-382 in flight (sibling worktrees), plus T-390 (surviving launcher follow-up).

## Test report

This wave log adds no source code changes; PR #304 carried T-387's tests. Consolidated `make quality` for the bundled PR #305 will be re-verified after this work log lands.
