# CLAUDE.md — cloglog

## Project Overview

cloglog is a multi-project Kanban dashboard for managing autonomous AI coding agents running in agent-vm sandboxes.

**This project uses the cloglog plugin** (`plugins/cloglog/`) for workflow discipline — planning pipeline, PR workflow, agent lifecycle, and worktree management. Generic workflow rules are provided by the plugin. This file contains cloglog-specific instructions.

## Architecture

DDD bounded contexts — each context owns its own models, services, repository, and routes:

- **Board** (`src/board/`) — Projects, Epics, Features, Tasks, status roll-up
- **Agent** (`src/agent/`) — Worktrees, Sessions, registration, heartbeat
- **Document** (`src/document/`) — Append-only document storage
- **Review** (`src/review/`) — PR review turn registry (`pr_review_turns`); exposes `IReviewTurnRegistry` as an Open Host Service consumed by Gateway. Gateway imports the protocol only, never `models.py` or `repository.py`.
- **Gateway** (`src/gateway/`) — API composition, auth, SSE, CLI. **Owns no tables.**

Contexts communicate through interfaces defined in `interfaces.py`, never by importing each other's internals. Full context map + ubiquitous language: `docs/ddd-context-map.md`. Agent lifecycle protocol: `docs/design/agent-lifecycle.md`.

## Worktree Discipline

If you are working in a worktree (`wt-*` branch), you MUST only touch files in your assigned context. Directory mappings live in `.cloglog/config.yaml` under `worktree_scopes`. Writes outside your scope are blocked by the `protect-worktree-writes` hook.

**Edit/Write `file_path` inside a worktree must include the `.claude/worktrees/<wt-name>/` prefix.** A `file_path` resolving to `/home/sachin/code/cloglog/src/...` (the main repo) goes through unguarded and lands in the main checkout, creating a ghost diff. Double-check every absolute `file_path` carries the worktree prefix.

## Commands

`make help` lists everything. The ones you use most:

- `make quality` — full gate (lint + typecheck + test + coverage + contract + demo-check). Must pass before any commit/PR — enforced by the `quality-gate` hook.
- `make invariants` — runs just the silent-failure pin tests listed in `docs/invariants.md`. Fast local check before pushing in a sensitive area.
- `make dev` — backend + frontend dev servers.
- `make db-up` / `make db-migrate` — PostgreSQL via Docker Compose + Alembic.

## Quality Gate

`make quality` is mandatory before completing any task or creating a PR. The `quality-gate` plugin hook runs it automatically on `git commit`, `git push`, and `gh pr create`.

## CI

Two PR-blocking workflows live in `.github/workflows/`:

- **`ci.yml`** — backend lint/typecheck/tests, frontend tests, MCP server tests, contract check, Playwright e2e (gateway/frontend changes only). Triggered by a `paths:` filter scoped to runtime code and tests.
- **`init-smoke.yml`** — plugin portability gate. Runs `tests/plugins/test_init_on_fresh_repo.py` and `tests/plugins/test_plugin_no_cloglog_citations.py` on **every PR** (no paths filter) so a change anywhere — plugin SKILL.md, hooks, docs, settings — cannot ship a regression that breaks `init` on a fresh downstream repo. Pinned by `tests/plugins/test_init_smoke_ci_workflow.py`.

## Git Identity & PRs

All pushes, PRs, and GitHub API calls MUST use the GitHub App bot identity. Use the `github-bot` skill — it has the exact commands for pushing, creating PRs, checking status, and replying to review comments. Never use `git push`, `gh pr`, or `gh api` without the bot token.

**Exception — branch-protection / ruleset inspection.** The App PEM (`scripts/gh-app-token.py`) only requests `contents`/`pull_requests`/`issues`/`workflows` permissions. APIs that require `administration:read` (e.g. `gh api repos/X/branches/Y/protection`) return `403 Resource not accessible by integration` against bot tokens. The `make verify-prod-protection` target therefore uses the operator's personal `gh auth` (NOT `BOT_TOKEN`); see the "Branch protection / verification" section below for details.

## Stop on MCP Failure

Halt on any MCP failure: startup unavailability emits `mcp_unavailable` and exits; runtime tool errors emit `mcp_tool_error` and wait for the main agent; transient network errors get one backoff retry before escalating.

Authoritative rule: `docs/design/agent-lifecycle.md` §4.1. The `prefer-mcp.sh` pre-bash hook blocks direct HTTP fallbacks. 5xx and 409 are NOT transient.

## Non-Negotiable Principles

1. **Always choose the best option, not the easiest.** Pick the architecturally sound solution even if it requires more work. Never take shortcuts that create tech debt.
2. **Boy Scout Rule: leave the code better than you found it.** Fix pre-existing problems in code you touch — broken tests, inconsistent naming, bugs.

## Silent-Failure Invariants → `docs/invariants.md`

Codebase-specific gotchas that can ship broken without automated catch live in `docs/invariants.md`. Each entry names the invariant and its pin test. Before pushing work that touches those areas, run `make invariants`. New incidents add an entry there, not here.

Structural DDD rules (router registration, gateway owns no tables, supervisor endpoints reject agent tokens, agent-facing route auth Depends) are carried by the `ddd-reviewer` subagent — spawn it on any PR that adds endpoints.

## Runtime & Deployment

cloglog, the MCP server, and every worktree agent share one host filesystem. The backend can read and write worktree paths directly. If that ever changes it will be a separate, explicit project — do not pre-design for it.

The prod worktree at `/home/sachin/code/cloglog-prod` tracks the `prod` branch (not `main`). `make promote` fast-forwards `prod` from `origin/main` and rotates workers. The dev worktree (this checkout) sits on `main`. PRs always target `main`; `prod` is fast-forward-only and pushed exclusively by `make promote`. Branch protection on `prod` is asserted by `make verify-prod-protection`. Full design: `docs/design/prod-branch-tracking.md`.

- Credentials live in three homes: `~/.cloglog/credentials` (project API key), `~/.agent-vm/credentials/<bot>.pem` (GitHub App private keys), backend `.env` (per-host knobs). See `docs/setup-credentials.md`.
- `CLOGLOG_API_KEY` never lands in `.mcp.json` — pin: `tests/test_mcp_json_no_secret.py`.
- The cloudflared tunnel is systemd-managed, not a `make prod` child — `scripts/preflight.sh` verifies it.
- After cloning the dev repo, run `bash scripts/install-dev-hooks.sh` once to install the pre-commit guard against direct `main` commits. The hook lets `ALLOW_MAIN_COMMIT=1` override only (rare — emergency-rollback cherry-picks). All other commits go via a `wt-*` branch + PR, including close-wave/reconcile fold commits — see `plugins/cloglog/skills/close-wave/SKILL.md` Steps 10/13 and `plugins/cloglog/skills/reconcile/SKILL.md` Step 5.

### Rollback path

If a bad commit is on `main` but **not yet promoted**: don't run `make promote`. Land a revert PR on `main`; the next `make promote` advances `prod` past both the bad commit and its revert.

If the bad commit is **already on `prod`** (someone ran `make promote` before noticing):

1. `make prod-stop` — stop gunicorn + frontend preview.
2. `git -C ../cloglog-prod reset --hard <last-known-good-sha>` — roll the prod worktree back. (Force-pushing `origin/prod` is acceptable here; if branch protection blocks it, lift the rule temporarily as the operator.)
3. `make prod` — restart on the rolled-back SHA.
4. Land a revert PR on `main` so the next `make promote` doesn't re-pull the bad commit.

Do NOT try to revert via PR on `prod` — `prod` is fast-forward-only by design.

## Tech Stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL
- Frontend: React 18, Vite, TypeScript, Vitest
- MCP Server: Node.js, TypeScript, @modelcontextprotocol/sdk
- Tools: uv, ruff, mypy, pytest
