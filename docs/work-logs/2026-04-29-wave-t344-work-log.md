# Wave: t344 — init skill mcpServers fix

**Date:** 2026-04-29
**Worktrees:** wt-t344-init-mcp-json-fix
**PRs:** #268

## Shutdown summary

| Worktree | PR | Shutdown path | Commits | Files |
|----------|-----|----------------|---------|-------|
| wt-t344-init-mcp-json-fix | #268 (merged 2026-04-29T13:59:38Z) | cooperative (agent_unregistered received via inbox before close-wave invocation) | 8 | 5 |

The agent emitted `pr_merged_notification` and then `agent_unregistered` to the supervisor inbox in the normal flow. The launcher's claude session stayed live in its zellij tab post-unregister (idle, no further work) — close-wave closed the tab via `zellij action go-to-tab-name … && close-tab`, the SIGHUP reached the launcher, the trap-based `unregister-by-path` fallback fired (the second call is a harmless no-op since the agent had already unregistered), and the process tree exited cleanly. No tier-2 force_unregister was needed.

## T-344 — Fix init skill: write mcpServers to .mcp.json, not .claude/settings.json

**PR:** [#268](https://github.com/sachinkundu/cloglog/pull/268) (merged 2026-04-29T13:59:38Z)

**Files touched:**
- `plugins/cloglog/skills/init/SKILL.md`
- `README.md`
- `docs/design.md`
- `tests/plugins/test_init_on_fresh_repo.py`
- `docs/demos/wt-t344-init-mcp-json-fix/exemption.md`

**Commits:**
```
8cdb436 demo: refresh exemption diff_hash for codex session 3 fix
a83661a docs(design): revert port to 8000 in walkthrough — matches make run-backend
745c32e demo: refresh exemption diff_hash for codex session 2 fix
f34eaa9 docs(design): correct MCP setup snippet — .mcp.json + 127.0.0.1:8001
a627c48 demo: refresh exemption diff_hash for codex-fix round
614248d fix(init): preserve non-cloglog mcpServers entries during T-344 repair
a5463f8 demo(t-344): exemption — init SKILL.md retarget is internal plumbing
3c632bc fix(init): write mcpServers to .mcp.json, not .claude/settings.json (T-344)
```

### What shipped (from `work-log-T-344.md`)

`/cloglog init` now writes `mcpServers.cloglog` to `.mcp.json` at the project root (the file Claude Code actually loads project-scoped MCP servers from), not into `.claude/settings.json`. Pre-T-344, freshly init'd projects had the block in the wrong file: `mcp__cloglog__*` tools never resolved and `/cloglog setup` failed with "register_agent doesn't exist".

The Step 3 Python merge is now two-file:
- `.claude/settings.json` ← `hooks.SessionStart` only.
- `.mcp.json` ← `mcpServers.cloglog` only.

Both writes are idempotent. A Phase 1.5 auto-repair migrates the legacy layout on re-run: it pops only the `cloglog` key out of `settings.mcpServers` and seeds it into `.mcp.json`. Sibling MCP server entries (e.g. `github`, `linear`) survive in `settings.json`. If `cloglog` was the only entry, the now-empty `mcpServers` key is dropped for a clean shape.

### Decisions (from per-task work log)

- **Two writes, two files, two responsibilities.** Splitting the merge makes the contract obvious — Claude Code reads `.mcp.json` for MCP, `.claude/settings.json` for hooks.
- **Migrate only `cloglog`, not the whole `mcpServers` map** (codex round 1 catch). `settings.pop("mcpServers")` would silently delete an operator's hand-maintained `github`/`linear` entries.
- **Absent-key vs cloglog-absent assertion.** Pin asserts `cloglog not in settings.mcpServers`, with a separate empty-after-migration assertion in the migration test.
- **Port in `docs/design.md` stays `127.0.0.1:8000`** (codex round 3 catch). The same walkthrough starts the backend with `make run-backend` (`:8000`); session 2's port flip to `:8001` introduced an internal contradiction.
- **Demo gate: classifier exemption.** Diff is plugin/test/docs only — no HTTP routes, MCP tool registrations, React components, CLI surfaces, or migrations. Verdict `no_demo`.

### Review findings + resolutions

| Session | Severity | Finding | Resolution |
| --- | --- | --- | --- |
| 1/5 | MEDIUM | `settings.pop("mcpServers")` would delete sibling MCP server entries on re-run | Pop only `settings["mcpServers"]["cloglog"]`; drop empty parent only if no siblings remain. New pin `test_step3_migration_preserves_non_cloglog_mcp_servers`. |
| 2/5 | HIGH | `docs/design.md:780-792` still told operators to put `mcpServers` in "your Claude Code settings" — would recreate the T-344 bug for anyone following design.md | Updated snippet to name `.mcp.json` at project root + point readers at `/cloglog init`. |
| 3/5 | MEDIUM | Session 2's port change introduced contradiction with the same walkthrough's `make run-backend` (which binds `:8000`) | Reverted port to `:8000`. File-location fix preserved. |
| 4/5 | `:pass:` | — | Auto-merge gate fired `ci_not_green` first (CI was still pending), waited via `gh pr checks --watch`, all checks green, re-evaluated → `merge`. |

### Residual TODOs

- **Downstream projects that ran the broken init have the wrong layout on disk.** The new auto-repair fixes them on the *next* run of `/cloglog init`. There is no proactive sweep; explicitly out of scope. If a downstream project has a stale layout and never re-runs init, `mcp__cloglog__*` tools will continue to fail there until they do.
- **`docs/design.md`'s example uses `:8000` (dev), but `.mcp.json` itself ships with `:8001` (prod default).** Intentional — the design.md snippet sits inside a `make run-backend` walkthrough for the dev backend. If a future task reorganises that section, the port reference needs to move with it.
- **`BRAND_SURFACE_SETTINGS = ("cloglog",)`** holds only in production where `CLAUDE_PLUGIN_ROOT` ends in `.../cloglog/...`. In the test fixture (`fake_plugin_root` named `plugin/`) the resolved bootstrap path doesn't carry the literal "cloglog", so the brand-surface assertion only runs on `.mcp.json`. If the fixture ever changes, revisit.

## Learnings & Issues

Integration verification: `make sync-mcp-dist` reported `mcp-server tool surface unchanged — no broadcast` (T-344 didn't touch the MCP tool surface). Quality gate on the close-wave branch is run in Step 10.5.

New durable learnings to fold into CLAUDE.md (candidates from the per-task log):

1. **`.mcp.json` is the only file Claude Code loads project-scoped MCP servers from.** `.claude/settings.json.mcpServers` is silently ignored by Claude Code's MCP loader. Any script that thinks "merge this MCP block into settings.json" is broken-by-construction. Pin: `tests/plugins/test_init_on_fresh_repo.py::test_step3_block_writes_settings_with_no_placeholders`.
2. **Migrations that move config between files must preserve sibling entries.** `settings.pop("mcpServers")` would silently delete every non-cloglog server alongside the migrated entry. The fix is to pop only the specific subkey and drop the parent only if it ends up empty. Generalises to any "consolidate config into one file" migration.
3. **Cross-doc port consistency check.** When updating an example URL, grep the surrounding doc for `make run-backend` / `make prod` / startup commands and verify the port matches what the reader was just told to start. Codex session 3 caught a port mismatch introduced while fixing the file-location issue.

(Item 1 is the most generally useful — folding into CLAUDE.md.)

## State After This Wave

- `/cloglog init` ships the correct `.mcp.json`-based layout for fresh projects.
- Existing projects auto-repair on next `/cloglog init` run.
- Init smoke test (CI-blocking on every PR via `init-smoke.yml`) covers both the fresh-write and migration paths.
- `~/code/antisocial` was repaired manually during the diagnosis session and is online.
