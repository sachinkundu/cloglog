# Wave: hooks + apikey fixes — 2026-04-20

Two follow-up fix PRs landed on the same day, one hardening the
agent-lifecycle hooks (B-2) and one closing the CLOGLOG_API_KEY disclosure
path in worktrees (T-214). Closed together because both were queued behind
the T-215 shutdown-path merge (PR #166) and share the worktree-create hook
as a touch point.

## Worktrees closed

| Worktree          | Branch            | PR   | Merged at (UTC)       | Commits |
|-------------------|-------------------|------|-----------------------|---------|
| wt-b2-hooks       | wt-b2-hooks       | #167 | 2026-04-20T14:07:02Z  | 1       |
| wt-t214-apikey    | wt-t214-apikey    | #168 | 2026-04-20T14:08:50Z  | 2       |

## PR #167 — fix(hooks): T-217 + T-219 + T-242

*SessionEnd trap, prefer-mcp hardening, shutdown-artifacts reset.*

Commit: `23a0268 fix(hooks): T-217 + T-219 + T-242 SessionEnd trap, prefer-mcp hardening, shutdown-artifacts reset`

Files touched:

- `.cloglog/on-worktree-create.sh`
- `.gitignore`
- `docs/demos/wt-b2-hooks/{demo.md,demo-script.sh}`
- `docs/design/agent-lifecycle.md`
- `plugins/cloglog/hooks/agent-shutdown.sh`
- `plugins/cloglog/hooks/prefer-mcp.sh`
- `plugins/cloglog/skills/launch/SKILL.md`
- `shutdown-artifacts/{work-log.md,learnings.md}` (demo fixtures)

## PR #168 — fix(mcp): T-214 stop exposing CLOGLOG_API_KEY

Commits:

- `3fd46ec fix(mcp): T-214 stop exposing CLOGLOG_API_KEY in worktree .mcp.json`
- `5c81503 fix(mcp): T-214 review fixes — sync stale docs + run mcp tests in quality gate`

Files touched:

- `.cloglog/on-worktree-create.sh`
- `.mcp.json`
- `Makefile`
- `docs/ddd-context-map.md`
- `docs/demos/wt-t214-apikey/{demo.md,demo-script.sh}`
- `docs/design.md`
- `docs/setup-credentials.md`
- `mcp-server/src/{credentials.ts,index.ts}`
- `mcp-server/tests/credentials.test.ts`
- `plugins/cloglog/hooks/{agent-shutdown.sh,worktree-create.sh}`
- `plugins/cloglog/skills/init/SKILL.md`
- `scripts/rotate-project-key.py`
- `tests/test_mcp_json_no_secret.py`

## Learnings & Issues

Quality gate on main after merge: **613 passed, 1 xfailed** (pre-existing
`pr_url_reuse_blocked_cross_feature`), **90.76 %** coverage, contract
compliant, demo verified. No fix-ups needed — both worktrees had rebased
before merging and `.mcp.json` / `on-worktree-create.sh` edits composed
cleanly.

Three durable rules promoted to `CLAUDE.md` → Runtime & Deployment
Assumptions:

1. **`CLOGLOG_API_KEY` belongs in `~/.cloglog/credentials` (0600), never in
   `.mcp.json`.** MCP server exits `78` (`EX_CONFIG`) if missing, pinned by
   `tests/test_mcp_json_no_secret.py`. Operators must migrate once per host
   (dev, prod, any alt-checkout) before the next worktree launches.
2. **`zellij action close-tab` does not signal its children** — they are
   reparented. The only reliable shutdown path is the launcher's bash trap,
   driven by `close-wave`'s explicit `kill <pid>`. Don't design lifecycle
   behavior that assumes `close-tab` triggers cleanup.
3. **`shutdown-artifacts/` is gitignored** — never commit its contents.
   `.cloglog/on-worktree-create.sh` resets the directory on every worktree
   bootstrap; an accidental commit on 2026-04-05 leaked stale files into
   every fresh worktree until T-242 removed them from tracking.

A fourth, operator-visible issue surfaced during close-wave itself and is
tracked separately (not part of either PR): `make prod` aborts with a port
collision when a prod gunicorn master is already running, and its trap
kills the vite preview on the way out — leaving the stack half-alive.
Needs an idempotence check on `make prod` before the port teardown.

## State After This Wave

- `.mcp.json` is secret-free in every live worktree; the no-secret guard
  runs in `make quality`.
- Agent shutdown hooks are signal-driven with a breadcrumb log; the
  launcher template runs Claude as a subprocess (not `exec`) so the trap
  can reach the backend's `/agents/unregister-by-path`.
- `prefer-mcp.sh` blocks direct backend calls across loopback aliases
  (`127.0.0.1`, `localhost`, `0.0.0.0`, `[::1]`) for curl, wget, httpie,
  python, and node. `CLOGLOG_ALLOW_DIRECT_API=1` is the inline escape
  hatch.
- Fresh worktrees start with an empty `shutdown-artifacts/` directory and
  a credentials sanity check in `on-worktree-create.sh`.
