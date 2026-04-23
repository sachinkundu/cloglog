# CLAUDE.md — cloglog

## Project Overview

cloglog is a multi-project Kanban dashboard for managing autonomous AI coding agents running in agent-vm sandboxes.

**This project uses the cloglog plugin** (`plugins/cloglog/`) for workflow discipline — planning pipeline, PR workflow, agent lifecycle, and worktree management. Generic workflow rules are provided by the plugin. This file contains cloglog-specific instructions.

## Architecture

DDD bounded contexts — each context owns its own models, services, repository, and routes:

- **Board** (`src/board/`) — Projects, Epics, Features, Tasks, status roll-up
- **Agent** (`src/agent/`) — Worktrees, Sessions, registration, heartbeat
- **Document** (`src/document/`) — Append-only document storage
- **Gateway** (`src/gateway/`) — API composition, auth, SSE, CLI

Contexts communicate through interfaces defined in `interfaces.py`, never by importing each other's internals.

For the full context map, relationship types, and ubiquitous language glossary, see `docs/ddd-context-map.md`.

The canonical agent lifecycle protocol (registration, shutdown, inbox events, three-tier teardown) lives in `docs/design/agent-lifecycle.md` — plugin skills and templates cite its §1/§2/§6 throughout.

## Worktree Discipline

If you are working in a worktree (`wt-*` branch), you MUST only touch files in your assigned context. The directory mappings are defined in `.cloglog/config.yaml` under `worktree_scopes`.

Do NOT modify files outside your assigned directories. If you need a change in another context, note it and coordinate.

**This is enforced by the cloglog plugin's `protect-worktree-writes` hook.** Writes to files outside your assigned directories will be blocked automatically.

**Edit/Write `file_path` inside a worktree must include the `.claude/worktrees/<wt-name>/` prefix.** The scope hook only blocks writes whose path is under the worktree. A `file_path` that resolves to `/home/sachin/code/cloglog/src/...` (the main repo) goes through unguarded — the write lands in the main checkout, creating a ghost diff that looks like the agent cross-contaminated main. Double-check every absolute `file_path` carries the worktree prefix before calling Edit or Write.

## Commands

```bash
make quality          # Full quality gate — must pass before completing any task
make test             # All backend tests
make test-board       # Board context tests only
make test-agent       # Agent context tests only
make test-document    # Document context tests only
make test-gateway     # Gateway context tests only
make test-e2e         # Backend E2E integration tests (pytest)
make test-e2e-browser # Playwright browser E2E tests (headless)
make lint             # Ruff linter
make typecheck        # mypy type checking
make run-backend      # Start FastAPI dev server
make dev              # Start both backend + frontend dev servers
make db-up            # Start PostgreSQL via Docker Compose
make db-down          # Stop PostgreSQL
make db-migrate       # Run Alembic migrations
make db-revision      # Create new Alembic migration
make contract-check   # Validate backend matches API contract
make coverage         # Run tests with coverage report
make sync-mcp-dist    # Rebuild mcp-server/dist + broadcast mcp_tools_updated to live agents
make db-refresh-from-prod  # Snapshot prod DB into dev DB (debug prod issues locally)
```

### Production

```bash
make prod             # Start prod server (gunicorn + vite preview) in foreground
make prod-bg          # Start prod in background (idempotent — fails fast if master already running)
make prod-logs        # Tail prod server logs
make prod-stop        # Stop prod backend + frontend (tunnel is systemd-managed, do NOT kill cloudflared)
make promote          # Zero-downtime deploy of origin/main to prod
```

### Frontend

```bash
cd frontend && make test    # Frontend tests (Vitest)
cd frontend && make lint    # TypeScript type check
cd frontend && npm run dev  # Start Vite dev server
```

### MCP Server

```bash
cd mcp-server && make test   # MCP server tests
cd mcp-server && make build  # Build TypeScript
```

## Environment Quirks

- **Run frontend tests from `frontend/` directory:** `cd frontend && npx vitest run`. Running from repo root causes `document is not defined` errors.
- **Run backend tests from repo root:** `uv run pytest` from `/home/sachin/code/cloglog`.
- **Worktree bootstrap runs `uv sync --extra dev` automatically.** The dev toolchain (`pytest`, `mypy`, `ruff`, `pytest-cov`) lives under `[project.optional-dependencies].dev`, not `[dependency-groups].dev`. If you hit a `ModuleNotFoundError` on a fresh `.venv` (e.g. `No module named 'respx'`), the root cause is almost always that `pytest` is missing from the venv and `uv run` fell back to a system shim — re-run `uv sync --extra dev` manually.
- **`mcp-server/dist/` is gitignored — you rebuild it, nothing else does.** It is listed in both the repo-root `.gitignore` and `mcp-server/.gitignore`. Do NOT commit `dist/`. Neither `on-worktree-create.sh` (only `npm install`s on `wt-mcp*` worktrees) nor CI (`.github/workflows/ci.yml` runs `npm ci` + tests, no `npm run build`) rebuilds it. If your change touches `mcp-server/src/`, run `cd mcp-server && make build` yourself — local MCP clients consume `mcp-server/dist/index.js` directly, and `scripts/demo-update-task-status.mjs` imports from `../dist/server.js`, so stale artifacts bite at runtime.
- **Hook scripts must parse `.cloglog/config.yaml` with `grep`+`sed`, never `python3 -c 'import yaml'`.** The project's PyYAML lives in the uv venv, not the global `python3` that hooks run under. A `python3 + yaml` snippet in a hook silently swallows `ImportError` and returns the default `http://localhost:8000`, so the POST lands on the wrong port and the caller appears to succeed. The precedent comment in `plugins/cloglog/hooks/agent-shutdown.sh:64-68` exists precisely because this bug has shipped more than once (latest: PR #179 round 1, `.cloglog/on-worktree-create.sh` close-off-task POST — tracked as T-259). If you need another config key, copy the `grep '^key:'` + `sed` pattern from that hook.

## Quality Gate

Before completing any task or creating a PR, run `make quality` and verify it passes.

**This is enforced by the cloglog plugin's `quality-gate` hook.** Any `git commit`, `git push`, or `gh pr create` will automatically run the quality command first and block if it fails.

## Git Identity & PRs

**All pushes, PRs, and GitHub API calls MUST use the GitHub App bot identity.** Use the `github-bot` skill for all GitHub operations — it has the exact commands for pushing, creating PRs, checking PR status, replying to comments, and CI recovery. Never use `git push`, `gh pr`, or `gh api` without the bot token.

## Stop on MCP Failure

Halt on any MCP failure: startup unavailability emits `mcp_unavailable` and exits; runtime tool errors emit `mcp_tool_error` and wait for the main agent; transient network errors get one backoff retry before escalating.

This rule is authoritative in `docs/design/agent-lifecycle.md` §4.1. A short restatement for agents working in this repo:

- **Startup unavailability** (ToolSearch returns no matches, or the first MCP call after register fails at the transport layer) → write an `mcp_unavailable` event to `<project_root>/.cloglog/inbox` and exit. Do not fall back to direct HTTP, `curl`, or `gh api` against the backend — the project API key in the worktree environment MUST NOT be used to work around MCP.
- **Runtime tool error** (HTTP 5xx, backend exception, 409 state-machine guard, auth rejection, schema error mid-task) → write an `mcp_tool_error` event to `<project_root>/.cloglog/inbox` carrying the failing tool name and error text, halt the current task, and wait on your inbox Monitor for main-agent guidance. A 409 is not advisory; it is the backend refusing the transition. Silent continuation after a guard rejection has already shipped broken work more than once — do not "press on."
- **Transient network errors** (`ECONNRESET`, `ETIMEDOUT`, fetch timeout) → one retry after ≥ 2 s backoff, then escalate to `mcp_tool_error` on the second failure. HTTP 5xx and 409 are NOT transient and MUST NOT be retried.

The `plugins/cloglog/hooks/prefer-mcp.sh` pre-bash hook enforces the "no direct HTTP" half of this rule; T-219 extends its coverage from load-time to runtime.

## Non-Negotiable Principles

These are CRITICAL. Every agent, every worktree, every task. No exceptions.

1. **Always choose the best option, not the easiest.** When proposing approaches, pick the architecturally sound solution even if it requires more work. Never take shortcuts that create tech debt. The right solution now saves pain later.

2. **Boy Scout Rule: leave the code better than you found it.** Fix pre-existing problems before adding new code. If you find broken tests, fix them first. If you find inconsistent naming, fix it. If you find a bug in code you're touching, fix it. Never pile new work on top of existing problems.

## Project-Specific Agent Instructions

These instructions are specific to cloglog's architecture and tech stack. They supplement the generic workflow rules provided by the cloglog plugin.

### Spec Phase — DDD Contract Design
- For features that add or modify API endpoints, spawn the `ddd-architect` agent to design the API contract following DDD principles (aggregate boundaries, ubiquitous language, context boundary respect).
- Spawn the `ddd-reviewer` agent to review the contract. Allow up to 3 revision rounds.
- The contract is an OpenAPI YAML file at `docs/contracts/<wave-name>.openapi.yaml`.

### Implementation Phase — Subagents
- **Spawn `test-writer`** for writing tests. It carries codified testing standards (real DB, no mocks, @testing-library/react patterns, coverage requirements). See `.claude/agents/test-writer.md`.
- **Spawn `migration-validator`** when touching database models. It validates Alembic migration files (revision chain, upgrade/downgrade, model imports).
- **Frontend worktrees need `cd frontend && npm install`** before tests will run — node_modules are not shared across worktrees.

### Runtime & Deployment Assumptions

cloglog, the MCP server, and every worktree agent share one host filesystem. There is no host/VM filesystem split. The backend can read and write worktree paths directly; no marshalling layer is needed. If that assumption ever changes it will be a separate, explicit project — do not pre-design for it.

- **Don't rely on transient filesystem probes to drive destructive state changes.** Alembic migrations in `src/alembic/versions/` must be additive-only with respect to live environment state. Destructive cleanup (marking agents offline, soft-deleting rows, rewriting columns) belongs in a reconciliation path (F-48 `/cloglog reconcile`), not in migrations that run on every deploy.
- **Upsert paths must preserve existing columns on partial input.** When an upsert accepts partial data (e.g., `upsert_worktree(branch_name=...)`), treat empty-string / null from the caller as "preserve existing," not "overwrite with empty." A transient probe failure or a reconnect must not clobber a populated column.
- **`Path.cwd()` in backend code is a filesystem fingerprint of the launcher, not an invariant.** The backend may be launched from dev (`/home/sachin/code/cloglog`), prod (`../cloglog-prod`), or eventually Railway. Any subprocess that reads files via `-C`/`cwd=` must take its root from `Settings`, not `Path.cwd()` — otherwise codex/tools see a different tree than the PR's merge target. See T-255.
- **`CLOGLOG_API_KEY` lives in `~/.cloglog/credentials` (0600), never in `.mcp.json`.** The MCP server resolves the key from env first, then the credentials file; missing → `process.exit(78)` (`EX_CONFIG`). `tests/test_mcp_json_no_secret.py` pins the "no secret in `.mcp.json`" invariant. Every host (dev, prod, alt-checkouts) must have the credentials file provisioned before the next worktree launches — see `docs/setup-credentials.md`. T-214.
- **Three credential homes, three distinct secret classes — don't cross-wire them.** (1) `~/.cloglog/credentials` holds only the backend project API key `CLOGLOG_API_KEY`. (2) `~/.agent-vm/credentials/<bot>.pem` holds GitHub App private keys — one `.pem` per reviewer/pusher bot (`github-app.pem` for push-claude, `codex-reviewer.pem`, `opencode-reviewer.pem`). Minted at runtime via JWT → `POST /app/installations/<id>/access_tokens` by `src/gateway/github_token.py`. (3) Backend `.env` holds per-host knobs (DB URL, ports, `GITHUB_WEBHOOK_SECRET`, `REVIEW_SOURCE_ROOT`). **App IDs and installation IDs are NOT secrets** — they are public identifiers hard-coded in `src/gateway/github_token.py` as `_<BOT>_APP_ID` / `_<BOT>_INSTALLATION_ID` constants. When adding a new reviewer bot, follow the `_CLAUDE_*` / `_CODEX_*` / `_OPENCODE_*` shape exactly; do not invent a Settings-based or env-based detour for App IDs (PR #187 round 1 did, had to revert). T-248 lessons.
- **`zellij action close-tab` does not signal the child processes in the tab — they are reparented.** Shutdown hooks in `plugins/cloglog/hooks/agent-shutdown.sh` only fire from the launcher's bash trap, which is driven by the explicit `kill <pid>` step in `close-wave`. Don't design agent-lifecycle behavior that assumes `close-tab` triggers cleanup. B-2 / T-217.
- **`shutdown-artifacts/` is `.gitignore`d — never commit its contents.** The directory is re-created clean by `.cloglog/on-worktree-create.sh` on each worktree bootstrap. An accidental commit of `shutdown-artifacts/learnings.md` on 2026-04-05 made every subsequent worktree inherit stale files until T-242 removed them from tracking; don't re-introduce that.
- **The cloudflared tunnel is a systemd-managed service, not a `make prod` child process.** `docs/contracts/webhook-pipeline-spec.md:405-415` mandates `sudo cloudflared service install`; `scripts/preflight.sh` checks `pgrep -x cloudflared`; `docs/review-engine-e2e.md` expects `systemctl status cloudflared` healthy. Never auto-start/kill `cloudflared` from the Makefile (PR #174 tried that and #176 reverted it after codex + user review caught the systemd coupling issue). `make prod`/`make prod-bg` call `scripts/preflight.sh`, which is where the "is the tunnel up?" question is answered.
- **Inside a worktree, `git rev-parse --show-toplevel` returns the worktree path, not the main clone.** When a shell script or hook inside a worktree needs "the main clone's root" — e.g., to reach the supervisor inbox at `<main-clone>/.cloglog/inbox` or a shared config — use `dirname "$(git rev-parse --git-common-dir)"` instead. T-243 agent-shutdown backstop hit exactly this trap.

### Pydantic Schema Gotcha
- **When adding a field to an API update call, verify the Pydantic schema includes it.** `model_dump(exclude_unset=True)` silently drops fields not in the schema — the API returns 200 but nothing is saved. No error, no warning. Always grep for the `XUpdate` model and confirm the field exists before assuming the API will persist it.
- **Parser normalization paths drop unknown fields silently — three-layer update required.** `src/gateway/review_engine.py::_parse_output` rewrites Codex-schema JSON into a narrow `{verdict, summary, findings}` dict before validating against `ReviewResult`. A new top-level field (e.g., `status` for consensus) disappears at this step unless the normalization explicitly copies it through. When extending a structured-output contract, update ALL THREE: (1) the JSON schema file (`.github/codex/review-schema.json`), (2) the Pydantic model (make field `Optional` with a default), and (3) the normalization path — explicit `data.get("<field>")` + copy into the rewritten dict. Ship a pin test that constructs a payload with the field, parses it, and asserts survival. Caught as HIGH on PR #187 round 1.

### `get_board` Payload Size
- **`mcp__cloglog__get_board()` without filters returns ~100KB+** (every epic, feature, task with full descriptions) which exceeds typical MCP tool-output limits. Even filtering by `epic_id` can be tens of KB. Agents that just need an index should redirect the response to a file and `Grep` for what they want — or, better, use the targeted tools (`list_epics`, `list_features`, `get_my_tasks`) when applicable. A `fields` projection is tracked as a backlog improvement.

### Debugging Persistence Bugs
- **Check the DB before writing code.** For any "X doesn't persist on refresh" bug: (1) check DB state, (2) reproduce the action, (3) check DB again. If unchanged -> write path is broken. If changed -> read/render path is broken. One query narrows the problem instantly.
- **Restart Vite for structural changes.** New imports, new components, JSX restructuring — restart the dev server. HMR silently fails on structural changes and the browser keeps running old JavaScript with no visible error.

### Cross-Context Integration
- **Bundled-PR task sequencing: the single-active-task backend guard is real.** An agent assigned two tasks that ship as one PR (e.g., Wave C's `T-216 + T-243`) cannot have both `in_progress` simultaneously. Correct sequence: start task A, implement both, open the single PR, move A to `review`; after merge call `mark_pr_merged(A)` → `start_task(B)` → `update_task_status(B, review, pr_url=same)` → `mark_pr_merged(B)`. Drop an `add_task_note` on task B at PR time so the board state is self-explanatory.
- **Target-state docs must label and link their gaps.** Plugin docs sometimes describe a flow that depends on backend/consumer work not yet landed. Instead of reverting to a known-broken flow to "stay accurate," write the target state AND add a prominent **BACKEND GAP — T-NNN** (or similar) line that names the offending backend file+line, the tracking task, and the operational mitigation (usually: emit a specific event to the main inbox and wait). Future readers know what works today vs what will work when X lands, without spelunking git history. Pattern from T-216/T-243 round 1+2 findings.
- **Router registration:** If your context has `routes.py`, it MUST be registered in `src/gateway/app.py` via `app.include_router()`. If you can't edit `app.py` due to worktree discipline, add a comment at the top of your routes.py noting it needs registration, and mention it in your PR description.
- **Alembic migrations:** Your migration's `down_revision` must point to the latest existing migration, not just the one that existed when your worktree branched. If another context merged a migration before you, rebase and update your `down_revision` before pushing. Check with `python -m alembic history`.
- **Auth consistency:** All agent-facing endpoints use `Authorization: Bearer <api-key>`. Dashboard-facing endpoints are public (no auth). Never use query parameters for auth. Use the `CurrentProject` dependency from `src/gateway/auth.py`.
- **`/api/v1/agents/*` is a permissive auth bucket — per-route dependencies are load-bearing.** The gateway middleware in `src/gateway/app.py` lets any `Authorization` header through for `/api/v1/agents/*` and defers the real check to each route's `Depends(...)`. A new agent route added without an explicit `SupervisorAuth` / `CurrentProject` / `CurrentAgent` dependency is silently open — a bare `Bearer totally-invalid-token` returns 200. Every new agent-facing endpoint MUST declare its auth dep and ship a test that POSTs an arbitrary token and asserts 401. Caught as a MEDIUM on PR #178 (`request_shutdown` shipped without a dep; attacker with a worktree UUID could force any agent to shut down).
- **Supervisor / destructive endpoints must reject the agent's own token, not just "authenticate."** `SupervisorAuth` accepts project keys + the MCP service key; `CurrentAgent` accepts agent tokens. A "kill the wedged agent" or "force-unregister" route that reuses `CurrentAgent` lets the wedged agent unregister itself, defeating the whole point. Use `McpOrProject` (or define a new dep) that explicitly excludes agent tokens, and add a regression test named `test_*_rejects_agent_token`. T-221 / PR #178.
- **Non-agent routes accepting MCP credentials MUST declare `CurrentMcpService` or `CurrentMcpOrDashboard` as a `Depends`.** `ApiAccessControlMiddleware` in `src/gateway/app.py` only presence-checks credential headers on non-agent routes — it does NOT validate the bearer value. A new route added without the Depends is silently open to ANY bearer under `X-MCP-Request: true`. This is distinct from the `/api/v1/agents/*` bucket hole above — that one gates on the Authorization header; this one was specifically the `list_worktrees` endpoint accepting garbage MCP bearers because no per-route Depends ran. Always add a regression test named `test_*_rejects_invalid_mcp_bearer` that calls the route with its real HTTP method — GET, POST, whatever the route declares — passing a bogus bearer + `X-MCP-Request: true`, and asserts 401. The motivating case (`list_worktrees`) is a GET; a blind `POST` in the test would hit the wrong method behavior rather than exercising the per-route Depends. See `tests/e2e/test_access_control.py::test_worktrees_with_invalid_mcp_bearer_is_rejected` for the exact shape. Caught by codex on PR #191 round 2 (T-258); the hole was dormant for months. See `docs/ddd-context-map.md § Auth Contract` for the full route-prefix → credential-shape table.
- **Concurrent worktree merges:** When multiple worktrees are active, the last to merge faces conflicts in shared files (`events.py`, `schemas.py`, `types.ts`, `package.json`). Plan for this — rebase frequently and resolve conflicts before requesting review.
- **Model imports in tests:** All model classes must be imported in `tests/conftest.py` so `Base.metadata.create_all` creates all tables. If you add a new model, verify the import exists.
- **Refactoring webhook resolver short-circuits:** when editing a resolver that returns `None` at multiple gates (auth guard, project-match guard, branch-match guard), lift the gate conditions to a flat list at the top of the function and re-verify every `None` return is still reachable from foreign/malformed input. Moving a gate inside a new conditional can silently widen the surface. Load-bearing for `_resolve_agent` in `src/gateway/webhook_consumers.py`; caught as a second-round finding on PR #164.
- **Path-composition conventions have three sides:** the writer, the verifier, and the lookup. When fixing path-building code, `grep -rn` for every consumer of the path convention (e.g. `FEATURE_NORM`, `rev-parse --abbrev-ref HEAD`, `docs/demos/`) before pushing. T-251's first cut fixed only the writer; `scripts/run-demo.sh` (the lookup) needed the same normalization — caught in review.
- **`get_board` does not expose worktree metadata — use `list_worktrees` for agent/worktree state.** `TaskCard` carries only task fields plus `worktree_id`; `last_heartbeat`, `worktree_path`, and worktree `status` live on `WorktreeResponse` (`src/agent/schemas.py:113-124`) reachable via `mcp__cloglog__list_worktrees()`. Any skill that needs to detect wedged agents or map worktree paths to UUIDs must call `list_worktrees`, not `get_board`. Caught as a CRITICAL on PR #182 round 1.
- **Gateway owns no tables — new review/webhook-adjacent persistence gets its own bounded context with an Open Host Service factory.** `docs/ddd-context-map.md` says "Gateway owns: no tables" and `docs/contracts/webhook-pipeline-spec.md:29` restates the rule for the review engine. When a new pipeline artifact needs persistence (e.g., `pr_review_turns` in T-248), create `src/<context>/` with `models.py` + `interfaces.py` (Protocol) + `repository.py` + `services.py`. Gateway imports ONLY `src.<context>.interfaces` + `services` (for factory functions), NEVER `models.py` or `repository.py` — lazy imports inside functions also count as violations. The factory (e.g., `make_review_turn_registry(session)`) is the Open Host Service entry point; its return type is the Protocol and the concrete class is hidden inside the function body. Caught as CRITICAL on PR #187 round 2 — initial `_RegistryCtx` did a lazy `from src.review.repository import ReviewTurnRepository` and reviewers called it a priority-3 violation.
- **Webhook redelivery needs four rules together; dropping any one breaks idempotency silently.** `webhook_dispatcher` deduplicates by `delivery_id`, but GitHub sends different delivery IDs for the same logical event (retries, `synchronize` on the same SHA). For a per-turn persisted loop like `pr_review_turns`: (1) **claim-before-run** via `INSERT ... ON CONFLICT DO NOTHING` — if the INSERT touches zero rows, abort; (2) **short-circuit on persisted consensus** — if any prior turn on `(pr_url, head_sha, stage)` has `consensus_reached=True`, return immediately; (3) **failed-turn retry** — a `status='failed'` row must allow later delivery to re-run that turn number via a `reset_to_running` helper; (4) **next-turn computation** — when resuming, pick the lowest `failed` turn before falling back to `max(turn_number) + 1`, or a post-failed turn 1 is skipped and its findings are lost. Also: when `post_review` returns False, call `complete_turn(status="failed")` and `break` — do NOT advance turn counting as if the post succeeded, or the registry looks complete while the author never saw the findings. T-248 PR #187 round 1 findings.
- **Capture the inbox offset *before* calling `request_shutdown`, not after.** `request_shutdown` returns as soon as the worker-inbox line is written; a fast agent can append `agent_unregistered` in the gap before the caller snapshots the file size. If the snapshot is taken post-call, the real event looks "already present" and the helper waits the full timeout before escalating to `force_unregister`. Pattern: `SINCE_OFFSET=$(stat -c %s "$MAIN_INBOX" 2>/dev/null || echo 0)` then call `request_shutdown`. Fixed in `scripts/wait_for_agent_unregistered.py` (PR #182 dbd38c9).

### API Contract Enforcement
- **Frontend worktrees**: Import API types from `generated-types.ts` (auto-generated from the contract). NEVER hand-write API response types.
- **Backend worktrees**: Implement endpoints matching the contract exactly. Run `make contract-check` before committing.
- If you need to change the API shape, STOP and update the contract first — don't work around it.
- `make quality` validates contract compliance automatically. Your commit will be blocked if your implementation drifts from the contract.

### Test Determinism
- **Don't derive "a different value" from string-splicing one uuid.** A test that built `sha_b = "b" + sha_a[1:]` from a uuid-derived `sha_a` was 1/16 flaky — whenever `uuid.uuid4().hex[0]` happened to be `"b"`, `sha_b == sha_a` and the "different SHA" claim silently held. Generate uniquely-different values from independent uuids, and add a defensive `assert a != b` so regressions fail loudly instead of intermittently. T-248 CI caught this after local green.

### Ruff Linting
- **`raise ... from None`** in except clauses — ruff B904 requires this for `raise HTTPException` inside `except` blocks.
- **Prefer `StrEnum` over `class X(str, Enum)`** — ruff UP042 flags the mixin form. `from enum import StrEnum` (Python 3.11+) is the project's standard for string enums.

### Infrastructure Isolation
- **Each worktree has its own ports and database.** Created by `.cloglog/on-worktree-create.sh`.
- Port assignments are in the worktree's `.env` file. Source `scripts/worktree-ports.sh` for env vars.
- Database is named `cloglog_<worktree_name>` (hyphens replaced with underscores).
- Never hardcode ports. Always use `$BACKEND_PORT`, `$FRONTEND_PORT` from the env.

### Proof-of-Work Demos (cloglog-specific)
- **Prove with OK/FAIL booleans, not repo-wide counts.** `grep -c foo plugins/ | wc -l` = 8 is a snapshot — any unrelated future doc that happens to mention `foo` bumps it to 9 and breaks byte-exact `showboat verify` on an old branch without the underlying behaviour regressing. Reduce to per-file booleans scoped to the exact files under audit. Caught in T-216/T-243 round 2 review.
- **Demo scripts must grep `mcp-server/src/*.ts`, not `mcp-server/dist/*.js`.** `scripts/run-demo.sh` starts backend + frontend and runs the feature demo; it does NOT `cd mcp-server && make build` first. `mcp-server/dist/` is gitignored, so under `set -euo pipefail` the first grep against `dist/` exits 2 before any proof is captured. Source is what ships to git and what reviewers check out — point every MCP-tool demo at `src/`. Caught as a HIGH on PR #178 round 1.
- **Backend PRs:** Use Showboat `exec` blocks to curl each new/changed endpoint. Start the backend on your worktree port first.
- **MCP server PRs:** Curl the backend endpoint AND launch a fresh Claude session in a zellij tab to call the actual MCP tool.
- **Frontend PRs:** Use Rodney (headless Chrome via `uvx rodney`) to take screenshots.
- Each worktree runs on isolated ports. Source `scripts/worktree-ports.sh` in demo scripts.
- **Demo determinism guidance lives in `plugins/cloglog/skills/demo/SKILL.md`** — showboat `verify` is byte-exact; reduce non-deterministic output (timings, tokens, PIDs, timestamps) before capture. See the "Determinism" note under the demo-check section of that skill.
- **`uvx showboat init` refuses to overwrite an existing `demo.md` — always `rm -f "$DEMO_FILE"` first.** A demo script that does not delete the file before `showboat init` will fail on any re-run (e.g., `make demo` run twice, or `showboat verify` after a fresh checkout). Add `rm -f "$DEMO_FILE"` as the first line of every demo script. Caught as a MEDIUM on PR #183 round 1.
- **Demo scripts must not call `uv run pytest` — `conftest.py` has a session-autouse Postgres fixture.** Any `pytest` invocation triggers `tests/conftest.py`'s session-autouse fixture, which connects to PostgreSQL and creates a temp database. `uvx showboat verify` runs without a live DB, so such demos pass `make demo` but fail `make quality` on a clean checkout. For verify-safe proof of test assertions, import the test module directly: `python3 -c "import sys; sys.path.insert(0, 'tests'); import test_foo as t; t.test_bar()"`. Caught as a HIGH on PR #183 round 2.

---

*This section is updated after each wave with learnings from PR reviews. If you encounter a new pattern that future agents should know, note it in your PR description so it can be added here.*

## Tech Stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL
- Frontend: React 18, Vite, TypeScript, Vitest
- MCP Server: Node.js, TypeScript, @modelcontextprotocol/sdk
- Tools: uv, ruff, mypy, pytest
