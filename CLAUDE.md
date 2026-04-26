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

The prod worktree at `/home/sachin/code/cloglog-prod` tracks the `prod` branch (not `main`). `make promote` fast-forwards `prod` from `origin/main` and rotates workers. The dev worktree (this checkout) sits on `main`. PRs always target `main`; `prod` is fast-forward-only and pushed exclusively by `make promote`. Branch protection on `prod` is asserted by `make verify-prod-protection`. Full design: `docs/design/prod-branch-tracking.md`.

- Credentials live in three homes: `~/.cloglog/credentials` (project API key), `~/.agent-vm/credentials/<bot>.pem` (GitHub App private keys), backend `.env` (per-host knobs). See `docs/setup-credentials.md`.
- `CLOGLOG_API_KEY` never lands in `.mcp.json` — pin: `tests/test_mcp_json_no_secret.py`.
- The cloudflared tunnel is systemd-managed, not a `make prod` child — `scripts/preflight.sh` verifies it.

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
- **`git checkout <branch> -- <path>` is path-scoped and ignores worktree locks.** A locked branch (checked out in another worktree) blocks `git checkout <branch>` (HEAD-changing) but not `git checkout <branch> -- <path>`. When reasoning about worktree-lock consequences, only HEAD-changing checkouts and pulls are affected; pathspec-scoped operations work as normal.
- **For long-lived branches, `git merge origin/main` beats `git rebase origin/main` on conflict economics.** A 10-commit branch rebased against an advanced `main` surfaces conflicts at every replayed commit that touches a shared file; merge resolves the same conflicts once. Use rebase only for short clean linear history before first review.

### Inbox monitor

- **`tail -n 0 -F` is the only correct default for inbox monitors.** `tail -f` exits if the file is missing (inbox is created lazily by the first webhook write); `tail -F` truncates event history to the last 10 lines; `tail -n +1 -F` re-delivers already-handled `pr_merged` / `review_submitted` and trips the one-active-task guard. Always pre-create the file (`mkdir -p .cloglog && touch .cloglog/inbox`) and use absolute paths — relative paths evade dedupe filters that match on absolute path equality.

### Protocol & schema propagation

- **Pre-flight grep before changing an inbox event shape, MCP response, or agent-instruction wording.** Sweep `plugins/cloglog/skills/*/SKILL.md`, `plugins/cloglog/agents/*.md`, `plugins/cloglog/templates/*.md`, `plugins/cloglog/hooks/*.sh`, `src/agent/schemas.py`, `src/agent/services.py` (hand-built response dicts that bypass `model_validate`), `docs/contracts/baseline.openapi.yaml` AND `frontend/src/api/generated-types.ts` (regenerate with `scripts/generate-contract-types.sh <abspath>`), and `docs/design/agent-lifecycle.md`. Bundle every hit in round 1 — each missed hit costs one Codex session against the 5-session cap.
- **`from_attributes=True` hides hand-built-dict drift.** Adding a required field to a Pydantic model with `from_attributes=True` works for callers that go through `Model.model_validate(orm_row)` but silently breaks any caller that hand-builds the dict (`{"id": ..., "title": ...}`). Grep for hand-built dict patterns matching the model's field set whenever you add a required field.
- **`async def` route handlers are `AsyncFunctionDef` in `ast.walk`, not `FunctionDef`.** Demo proofs that filter `ast.FunctionDef` will silently skip async routes. Use `isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))` for any route-handler inspection.
- **Cross-language demo proofs need each language's own interpolation token.** Pinning URL parity between `src/gateway/cli.py` (Python f-strings: `{var}`) and `mcp-server/src/tools.ts` (TS template literals: `${var}`) requires grepping with each language's actual syntax — a TS-shape grep silently fails on Python.

### Branch protection / verification

- **GitHub App PEM has no `administration` scope.** `scripts/gh-app-token.py` mints installation tokens with `contents`/`pull_requests`/`issues`/`workflows` only. Any `gh api repos/.../branches/<br>/protection` call against a bot token returns `403 Resource not accessible by integration`. Branch-protection inspection targets MUST use the operator's personal `gh auth` (`gh auth login --scopes 'repo,admin:org'`), NOT `BOT_TOKEN`. Suppressing the 403 with `2>/dev/null` is worse than surfacing it — the check then misreports the policy state. Surface the API response, case-match it, and use distinct exit codes for credential issues vs policy violations.
- **Branch-protection assertions must be clause-by-clause, not "non-empty list".** A protection rule that allows only an App, only a team, or two human users can each defeat an "operator-only" promotion gate while a naive non-empty-count check still prints OK. For each spec clause emit a separate assertion with a specific failure message naming the offending principal. Rolled-up counts lose every interesting failure mode.
- **Personal repos can't use classic protection's `restrictions` (push-by-actor).** That field requires an org repo. On personal repos, use rulesets API (`gh api repos/X/rulesets`) instead — supports actor-bypass-list and works on personal repos. Verifier targets that need actor-restriction assertions must query rulesets, not classic `branches/<br>/protection`.

### Deployment ordering

- **Publish-the-pointer comes last.** When a remote ref (`origin/prod`, deploy tags, etc.) is the canonical "what is live" pointer, advance it AFTER the deploy block (build, migrate, worker rotation), not before. Pushing first creates a window where the ref advanced but the running service is still on the previous SHA — a silent lie any deploy tooling reading the ref will believe. Generalises beyond `make promote`: any "ground truth from a remote ref" pattern must update the ref only after the contract holds.
- **Retargeting `git pull` to ff-only is load-bearing once a worktree has a writable local branch.** Plain `git pull origin <branch>` happily creates a merge commit when the local branch has diverged. Skills that ran `git pull origin main` were safe while the dev worktree couldn't check out `main` (sat on detached HEAD); the moment the dev worktree got a writable local `main`, every `git pull` line became a hazard. Use `git fetch origin && git merge --ff-only origin/main` and surface divergence as an investigation prompt — never paper over with a merge commit. **When you change *who* checks out a branch, audit every `git pull` against that branch before shipping the worktree-arrangement change.**

### Auto-merge / PR gates

- **`gh pr view --json statusCheckRollup` has no `bucket` field.** That normalized enum exists only on `gh pr checks --json name,bucket`. `gh pr view` returns `conclusion`/`status` enums in CheckRun shape. `gh pr view` also rejects `--arg` (that flag is `gh api` / standalone `jq` only). Run any documented executable command sequence end-to-end before merging the docs that describe it.
- **`paths:` filter in `.github/workflows/ci.yml` produces empty `statusCheckRollup` on docs-only PRs.** Any auto-merge gate that treats "empty checks list" as "still pending" will deadlock those PRs. The semantically right answer is "no CI signal to wait for ⇒ green" (codex still ran; spec PRs are docs-only by intent).
- **Codex's `event="COMMENT"` is a body marker, not a GitHub approval.** A human `CHANGES_REQUESTED` review still blocks merge. Any auto-merge gate must fetch `gh api repos/.../pulls/<n>/reviews`, filter to non-bot users, group by login, take the latest review per author, and refuse the merge if any latest is `CHANGES_REQUESTED` — user-block fires before label/CI checks.

### Backwards-compat for documented contracts

- **When replacing a documented runtime contract, retire it end-to-end or chain a fallback.** Tests passing on the new path doesn't catch operators who set the old setting per the still-current `.env.example`. Either delete the setting + update docs in the same PR, or keep the old path as a fallback. Don't leave docs claiming behavior the code no longer provides.

### Demo classifier / exemption gate (F-51)

- **Allowlist regexes must be validated against the actual repo path tree.** Grep every path class before writing — a narrow-by-accident regex blocks the feature it enables (e.g., `plugins/*/hooks/` broke rollout PRs that touch `plugins/cloglog/skills/`; nested `package-lock.json` lives at `frontend/` and `mcp-server/`, not root).
- **Route rules: key on the decorator, not the filename.** When a subagent rule says "user-observable HTTP routes," match `@[A-Za-z_]*router\.(get|post|patch|put|delete)\(` across all bounded contexts — not `src/gateway/**/routes.py`.
- **Test fixtures that shortcut the production flow can hide the exact failure mode you care about.** Writing `exemption.md` untracked covers the happy path but misses self-invalidation: committing the file changes the diff bytes, changing the SHA256, invalidating the stored `diff_hash`. Pin tests should reflect the real agent flow, not a convenient untracked-file shortcut.
- **Two-dot vs three-dot `git diff` matters for diff_hash correctness.** `git diff A B` (two-dot) includes changes A has that B doesn't; `git diff A...B` (three-dot) is merge-base-to-B. When `A` is a resolved merge-base SHA both produce identical bytes; when `A` is a raw ref and main has advanced, two-dot includes main's new commits as "removed." Use three-dot in the classifier; document equivalence conditions explicitly at every hash-computation site.
- **Codex's 5-session cap is a hard ceiling; bundle the full scope correctly in round 1.** When a PR generates round-after-round of sibling-file findings the scope is still expanding — include every affected file before the first codex turn, or expect to hit the cap without approval.
