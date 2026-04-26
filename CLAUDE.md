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

## Agent Learnings

Durable gotchas discovered during worktree tasks. Each bullet is non-obvious and has caused a real failure.

### Showboat demos

- **`ast.unparse` substring checks need structural scoping.** `ast.unparse(Return_node)` prepends the `return` keyword — `"return"` contains `"turn"` — causing false positives. Always unparse `ret.value` (the expression), not the wrapping statement. Applies equally to `fn.args`, `node.test`, and other statement wrappers.
- **`uv run --quiet python` for demos that import project modules.** Plain `python3 - <<PY` works for stdlib-only proofs. Proofs that import project code need `uv run --quiet python - <<PY`; `--quiet` keeps stdout deterministic across runs.
- **Plain Python `import` does NOT trigger `conftest.py`.** `python -c "from tests.foo import bar; bar.TestX().test_y()"` runs the test method without activating pytest's conftest auto-discovery. Use this pattern when a Showboat proof needs test-asserted behaviour without the session-autouse Postgres fixture firing.

### review_engine plumbing

- **Opencode-only host has a hard constraint on `count_bot_reviews`.** `TestOpencodeOnlyHost::test_session_cap_check_skipped_when_codex_unavailable` pins that `count_bot_reviews` MUST NOT be called when `_codex_available=False`. Any future code that needs a prior session count must gate the HTTP call on `_codex_available` or pre-seed a fallback (`prior = 0`) before the capability-gated block.

### Worktrees

- **Fast-forward from `origin/main` before any diff-based tool.** A worktree created from a stale local `main` will show phantom diffs relative to `origin/main`. Run `git merge --ff-only origin/main` before the demo classifier, PR-body drafting, or any diff-based check.

### Demo classifier / exemption gate (F-51)

- **Allowlist regexes must be validated against the actual repo path tree.** Grep every path class before writing — a narrow-by-accident regex blocks the feature it enables (e.g., `plugins/*/hooks/` broke rollout PRs that touch `plugins/cloglog/skills/`; nested `package-lock.json` lives at `frontend/` and `mcp-server/`, not root).
- **Route rules: key on the decorator, not the filename.** When a subagent rule says "user-observable HTTP routes," match `@[A-Za-z_]*router\.(get|post|patch|put|delete)\(` across all bounded contexts — not `src/gateway/**/routes.py`.
- **Test fixtures that shortcut the production flow can hide the exact failure mode you care about.** Writing `exemption.md` untracked covers the happy path but misses self-invalidation: committing the file changes the diff bytes, changing the SHA256, invalidating the stored `diff_hash`. Pin tests should reflect the real agent flow, not a convenient untracked-file shortcut.
- **Two-dot vs three-dot `git diff` matters for diff_hash correctness.** `git diff A B` (two-dot) includes changes A has that B doesn't; `git diff A...B` (three-dot) is merge-base-to-B. When `A` is a resolved merge-base SHA both produce identical bytes; when `A` is a raw ref and main has advanced, two-dot includes main's new commits as "removed." Use three-dot in the classifier; document equivalence conditions explicitly at every hash-computation site.
- **Codex's 5-session cap is a hard ceiling; bundle the full scope correctly in round 1.** When a PR generates round-after-round of sibling-file findings the scope is still expanding — include every affected file before the first codex turn, or expect to hit the cap without approval.
