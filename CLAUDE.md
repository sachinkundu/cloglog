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

## Git Identity & PRs

All pushes, PRs, and GitHub API calls MUST use the GitHub App bot identity. Use the `github-bot` skill — it has the exact commands for pushing, creating PRs, checking status, and replying to review comments. Never use `git push`, `gh pr`, or `gh api` without the bot token.

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

- Credentials live in three homes: `~/.cloglog/credentials` (project API key), `~/.agent-vm/credentials/<bot>.pem` (GitHub App private keys), backend `.env` (per-host knobs). See `docs/setup-credentials.md`.
- `CLOGLOG_API_KEY` never lands in `.mcp.json` — pin: `tests/test_mcp_json_no_secret.py`.
- The cloudflared tunnel is systemd-managed, not a `make prod` child — `scripts/preflight.sh` verifies it.

## Tech Stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL
- Frontend: React 18, Vite, TypeScript, Vitest
- MCP Server: Node.js, TypeScript, @modelcontextprotocol/sdk
- Tools: uv, ruff, mypy, pytest
