# Wave: f48-db-creds (2026-05-03)

Two-worktree wave under F-48 (Agent Lifecycle Hardening). Both worktrees were launched in parallel from the same `origin/main` tip and merged within minutes of each other. Bundled into one close-wave PR.

## Worktree summary

| Worktree | Tasks | PRs | Shutdown path |
|----------|-------|-----|----------------|
| wt-t388-db-isolation | T-388 | #306 | cooperative (`agent_unregistered` at 11:40:33) |
| wt-t382-per-project-creds | T-382 | #307 | cooperative (`agent_unregistered` at 11:42:43) |

---

## T-388 — Database isolation: separate prod/dev/per-worktree DBs, fail loud on missing .env

PR: https://github.com/sachinkundu/cloglog/pull/306 (5 codex rounds; cap reached, human-merged)

### What shipped

`Settings.database_url` and `alembic.ini` no longer carry a default URL. Every backend / alembic / contract-tooling entrypoint now refuses to start without an explicit `DATABASE_URL` instead of silently selecting the prod `cloglog` DB.

Layered chokepoints that landed:

- **`src/shared/config.py`** — `database_url: str = Field(...)` (required, no default). Pydantic raises `ValidationError` naming the field if neither env nor `.env` supplies it.
- **`src/alembic/env.py`** — drops the inline `os.environ.get("DATABASE_URL")` read; imports `Settings` and uses `settings.database_url`. Single source of truth across app + migrations.
- **`alembic.ini`** — `sqlalchemy.url =` empty. Old hardcoded prod URL removed.
- **`scripts/worktree-infra.sh`** — `CREATE DATABASE` no longer has stderr suppressed via `2>/dev/null`; failures abort bootstrap with a clear error.
- **`scripts/check-contract.py` + `scripts/extract-openapi.py`** — each seeds `os.environ.setdefault("DATABASE_URL", "…/postgres")` before importing `create_app`. Documented local commands work on a fresh clone.
- **`scripts/sync_mcp_dist.py`** — no longer imports `Settings`. `_resolve_dashboard_secret` resolves from override → env → `.env` line → default. Decouples non-DB script from DB env.
- **`Makefile`** — new `dev-env` target creates `cloglog_dev` if missing (via `docker compose exec -T postgres psql ...`, no host `psql` required) and writes `.env` with `DATABASE_URL=…/cloglog_dev`. New `prod-env-guard` (prerequisite of `prod`/`prod-bg`/`promote`) refuses to deploy unless `../cloglog-prod/.env` carries a non-empty `^DATABASE_URL=postgresql` line. `dev` and `run-backend` wrap their alembic + uvicorn invocations with `env -u DATABASE_URL` so the generated `.env` wins over a stale shell export. `dev-env` runs DB-only inline preflight.
- **`tests/conftest.py`** — seeds placeholder `DATABASE_URL` via `os.environ.setdefault` *before* importing `src.*` so Settings can construct at import time. Per-test DBs unchanged.
- **`tests/test_database_url_required.py`** — new pin (5 cases): import-time raise, alembic.ini empty default, alembic env funnels through Settings, clean-subprocess runs of both check-contract.py and extract-openapi.py.
- **`docs/invariants.md`** — entry under Persistence.
- **`Makefile invariants`** — pin wired in.
- **`.github/workflows/ci.yml`** — `DATABASE_URL` env on the two `alembic upgrade head` steps. Playwright step deliberately does NOT carry it (playwright.config.ts manages its own `cloglog_e2e_test`).

### Codex review summary (T-388)

Five rounds; each round flagged a different surface, no round revisited a prior finding. All addressed:

- R1 (HIGH×3): preflight ordering, host psql dependency, inherited DATABASE_URL.
- R2 (CRITICAL+HIGH): contract-check fail, Playwright DATABASE_URL leak.
- R3 (CRITICAL×2 + HIGH): scripts self-seed, prod-env-guard.
- R4 (CRITICAL+HIGH): blank-value bypass, dev-env direct invocation hid Docker diagnosis.
- R5 (HIGH+CRITICAL): sync-mcp-dist Settings coupling, dev-env preflight too broad.

After R5 codex hit `MAX_REVIEWS_PER_PR=5` (T-376's new cap) and posted "Review skipped: max bot sessions". Operator merged manually after summary issue comment.

### Operator action required (T-388)

**Before next `make promote`:** `../cloglog-prod/.env` must add an explicit line:

```
DATABASE_URL=postgresql+asyncpg://cloglog:cloglog_dev@127.0.0.1:5432/cloglog
```

The new `prod-env-guard` will refuse to run `make prod` / `make prod-bg` / `make promote` until this line is present and non-empty. The guard prints the exact line. Intentional fail-loud — operator sees the problem before deploy, not mid-rotation.

---

## T-382 — Per-project credential resolution

PR: https://github.com/sachinkundu/cloglog/pull/307 (5 codex rounds; cap reached, human-merged)

### What shipped

A new per-project credential lookup layer between the `CLOGLOG_API_KEY` env override and the legacy `~/.cloglog/credentials` global file. Resolver order, mirrored in five places that all read project API keys:

1. `CLOGLOG_API_KEY` env (operator override).
2. `~/.cloglog/credentials.d/<project_slug>` — per-project file.
3. `~/.cloglog/credentials` — legacy global, kept for single-project hosts.

The slug derives from `.cloglog/config.yaml: project` (basename($PROJECT_ROOT) fallback), validated against `^[A-Za-z0-9._-]+$` to refuse path traversal.

**Fail-loud invariant (new, in `docs/invariants.md`):** once `~/.cloglog/credentials.d/<slug>` EXISTS, it MUST yield a usable key. Present-but-broken (unreadable / directory / blank) refuses fallback to the legacy global file — the legacy file may hold a different project's key, and silently sending it recreates the original silent-401 bug. TS throws `UnusableProjectCredentialsError`; bash hooks/launch return empty + log distinctively to `/tmp/agent-shutdown-debug.log`.

### Resolver mirroring (T-382)

Five mirrored resolver sites, three of which run before the agent has any tooling:

- `mcp-server/src/credentials.ts` — TS resolver with `findProjectRoot()` walk-up, `resolveProjectSlug()`, `loadApiKey()` with present-but-unusable refusal, new `UnusableProjectCredentialsError` class.
- `mcp-server/src/index.ts` — startup catches both `MissingCredentialsError` and `UnusableProjectCredentialsError`, exits 78.
- `plugins/cloglog/skills/launch/SKILL.md` — bash `_api_key` / `_project_slug` / `_read_credentials_file` inline (launch.sh heredoc).
- `plugins/cloglog/hooks/lib/resolve-api-key.sh` — NEW shared helper sourced by both hooks; routes through `lib/parse-yaml-scalar.sh` for slug parsing.
- `plugins/cloglog/hooks/agent-shutdown.sh` and `plugins/cloglog/hooks/worktree-create.sh` — both source `resolve-api-key.sh`.

The launch heredoc and the agent-shutdown / worktree-create hooks run in standalone bash with no plugin lib in scope at startup, so the TS / launch-heredoc / lib-helper triplet is the smallest cross-language coverage; the two hooks that CAN source the helper do.

### Operator-facing changes (T-382)

- `plugins/cloglog/skills/init/SKILL.md` — Phase-1 EXISTING_SLUG validation, Phase-2 PROJECT_SLUG derivation + empty guard, multi-project `credentials.d` write, repair text branching, Step 4a `project:` field. Renamed `project_name:` → `project:` (the former was read by nothing).
- `scripts/rotate-project-key.py` — prints both single-project and multi-project recipes; reads slug from host's own config.yaml.
- `docs/setup-credentials.md` (+ plugin mirror), `docs/invariants.md`, `docs/ddd-context-map.md` — all document the new model.

### Codex review summary (T-382)

Five rounds; codex traced the contract through every resolver path:

- R1 — `agent-shutdown.sh` and `worktree-create.sh` still on legacy resolver; PR description error ("each project has its own backend instance" — wrong; one shared backend, project-scoped keys).
- R2 — `/cloglog init` steered multi-project operators to `export CLOGLOG_API_KEY` instead of writing the per-project file; Step 4a template had `project_name:` (read by nothing).
- R3 — present-but-broken per-project file silently fell through to legacy global. Now both resolvers fail loud.
- R4 — `mcp-server/src/index.ts` startup catch missed `UnusableProjectCredentialsError`. Bash slug parser unified through `lib/parse-yaml-scalar.sh`. Rotation docs / glossary updated.
- R5 — Slug validation at every input boundary (init Phase-1 EXISTING_SLUG, Step-2 repair, PROJECT_SLUG derivation). Manual setup and `.mcp.json` migration in setup-credentials.md branched single-vs-multi-project. Rotation script no longer interpolates raw `project.name`.

After R5 codex hit `MAX_REVIEWS_PER_PR=5` and posted "Review skipped: max bot sessions". Operator merged manually.

### Operator note (T-382)

No backfill for existing operators. Hosts with an existing `~/.cloglog/credentials` global file pointing at one project keep working unchanged via the legacy fallback. Migration to per-project files happens organically when an operator runs `/cloglog init` for a new project on the same host or rotates a key. There is no `scripts/migrate-to-credentials-d.py` — by design, since the current global file's project is unknowable without operator input.

---

## Shutdown summary

| Worktree | `agent_unregistered` | Surviving launcher | Worktree removed | Branch (local + remote) |
|----------|----------------------|--------------------|------------------|--------------------------|
| wt-t388-db-isolation | 11:40:33 | yes — pattern matches T-390 (filed). Closed via `close-zellij-tab.sh`; launcher trap fired on HUP. | `git worktree remove --force` ok | local + remote `wt-t388-db-isolation` deleted |
| wt-t382-per-project-creds | 11:42:43 | yes — same pattern. | `git worktree remove --force` ok | local + remote `wt-t382-per-project-creds` deleted |

Both worktrees were launched **before** T-387 (PR #304) merged — so both ran on the install-cache plugin path, not the live-load path. The recurring "surviving launcher" symptom they exhibit is consistent with the cache-freeze hypothesis under T-390. The next worktree launched on a post-T-387 main is the one to test against — not these.

`make sync-mcp-dist` after both PRs merged: tool surface unchanged, no broadcast.

## Learnings & Issues

### Routing decisions

- **Both PRs documented their own invariants.** T-388 added the missing-`DATABASE_URL` entry to `docs/invariants.md` and wired the pin into `make invariants`. T-382 added the "wrong project's API key must never be sent — fail loud" entry. No additional routing in this wave log.
- **Codex `MAX_REVIEWS_PER_PR=5` cap fired on both PRs.** T-376 (just shipped) made the cap count posted reviews accurately, so this is the cap working as designed — both PRs were genuinely complex enough to surface five rounds of substantive findings, and the bot correctly stops there. Operator merged each manually after the bot posted "Review skipped: max bot sessions". No regression; design works.
- **Five mirrored resolver sites in T-382.** The shared `plugins/cloglog/hooks/lib/resolve-api-key.sh` helper is the smallest cross-language coverage that still works for the standalone bash sites (launch heredoc, agent-shutdown, worktree-create). Future contract changes have at most three independent sites to update (TS, launch heredoc, lib helper) instead of five. Documented in T-382's per-task work log.
- **T-388's "fail loud" pattern across multiple entrypoints.** The same shape as T-382's (`Settings.database_url` required field; subprocess scripts seed their own placeholders explicitly; `prod-env-guard` blocks deploy). Both PRs effectively land the same architectural invariant — "next-tier signal must be ENOENT, not generic null" — applied to two different surfaces. Already captured in T-382's per-task learnings; no further action.

### Cross-task notes

- **`mark_posted` + `count_posted_codex_sessions`** (T-376) drove this wave: every post-T-376 PR sees the cap on POSTED reviews, not session attempts. Codex on these two PRs ran 5 substantive rounds each — exactly what the cap is for.
- **T-387 plugin-cache fix** is now in main but did NOT apply to either of these worktrees (they were launched off pre-T-387 origin/main). Their surviving-launcher behaviour is consistent with the install-cache hypothesis.

## State after this wave

- `DATABASE_URL` is required everywhere; missing-env fails loud at every entrypoint (backend, alembic, contract scripts).
- Per-project credentials work on multi-project hosts via `~/.cloglog/credentials.d/<slug>` with the legacy global as a single-project fallback.
- Both worktrees torn down clean (local + remote branches gone, worktrees removed, MCP dist rebuilt — surface unchanged).
- F-48 backlog still has T-390 (surviving-launcher follow-up — hypothesis: T-387 self-corrects), plus T-311, T-378, T-370, T-354, T-341, T-267 prioritized.

## Test report

This wave log adds no source code changes; PRs #306 and #307 each carried their own integration suites and `make quality` runs. Consolidated `make quality` for the bundled close-wave PR will be re-verified after this work log lands.

- T-388 PR #306 final: 1268 passed / 1 skipped / 1 xfailed; coverage 88.61%; `make invariants` 98 passed.
- T-382 PR #307 final: full quality gate passed at merge (33 new pin tests added across TS, bash, and python).
