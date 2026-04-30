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

## Agent Learnings

Durable gotchas discovered during worktree tasks. Each bullet is non-obvious and has caused a real failure.

### Showboat demos

- **`ast.unparse` substring checks need structural scoping.** `ast.unparse(Return_node)` prepends the `return` keyword — `"return"` contains `"turn"` — causing false positives. Always unparse `ret.value` (the expression), not the wrapping statement. Applies equally to `fn.args`, `node.test`, and other statement wrappers.
- **`uv run --quiet python` for demos that import project modules.** Plain `python3 - <<PY` works for stdlib-only proofs. Proofs that import project code need `uv run --quiet python - <<PY`; `--quiet` keeps stdout deterministic across runs.
- **Plain Python `import` does NOT trigger `conftest.py`.** `python -c "from tests.foo import bar; bar.TestX().test_y()"` runs the test method without activating pytest's conftest auto-discovery. Use this pattern when a Showboat proof needs test-asserted behaviour without the session-autouse Postgres fixture firing.
- **Ruff N806: uppercase variables inside functions are flagged.** Test helper variables like `LIFECYCLE = REPO_ROOT / "..."` MUST be lowercase when written inside a function body. Only module-level constants are exempt. Trips a clean-looking PR after every codex-fix round if you reach for ALL_CAPS for path constants in test helpers.

### Supervisor / agent lifecycle

- **`get_active_tasks` vs `get_my_tasks` scope difference is load-bearing.** `get_my_tasks` is scoped to the *caller's* registration. The main-agent supervisor cannot use it to ask "does worktree X still have backlog tasks?" — it returns the supervisor's own list. The supervisor's `agent_unregistered` handler MUST use `get_active_tasks` filtered by `worktree_id`. Silent-failure mode: `get_my_tasks` returns empty, supervisor concludes "no more tasks", prematurely triggers close-wave on a worktree that still had backlog work.

### review_engine plumbing

- **Opencode-only host has a hard constraint on `count_bot_reviews`.** `TestOpencodeOnlyHost::test_session_cap_check_skipped_when_codex_unavailable` pins that `count_bot_reviews` MUST NOT be called when `_codex_available=False`. Any future code that needs a prior session count must gate the HTTP call on `_codex_available` or pre-seed a fallback (`prior = 0`) before the capability-gated block.

### Worktrees

- **Fast-forward from `origin/main` before any diff-based tool.** A worktree created from a stale local `main` will show phantom diffs relative to `origin/main`. Run `git merge --ff-only origin/main` before the demo classifier, PR-body drafting, or any diff-based check.
- **`git checkout <branch> -- <path>` is path-scoped and ignores worktree locks.** A locked branch (checked out in another worktree) blocks `git checkout <branch>` (HEAD-changing) but not `git checkout <branch> -- <path>`. When reasoning about worktree-lock consequences, only HEAD-changing checkouts and pulls are affected; pathspec-scoped operations work as normal.
- **For long-lived branches, `git merge origin/main` beats `git rebase origin/main` on conflict economics.** A 10-commit branch rebased against an advanced `main` surfaces conflicts at every replayed commit that touches a shared file; merge resolves the same conflicts once. Use rebase only for short clean linear history before first review.

### EventBus / cross-worker

- **Postgres `NOTIFY` echoes back to the publishing connection.** Any cross-process pub/sub layered on LISTEN/NOTIFY must dedupe by a per-process `source_id` embedded in the payload — otherwise the publisher sees every event twice (local fan-out + LISTEN echo). Pin: `tests/shared/test_event_bus_cross_worker.py::test_publisher_does_not_double_deliver_its_own_notify_echo`.
- **Cross-worker mirrors must distinguish project subscribers from `subscribe_all()` (global) subscribers.** A global consumer that does write-side work (e.g., `notification_listener` inserting a row) runs on every gunicorn worker. Mirrored events go to project subscribers only; the originating worker handles global delivery via local fan-out. Otherwise N workers do the same write for one logical event. Pin: `test_mirrored_events_do_not_reach_global_subscribers`.
- **Postgres `NOTIFY` payload caps at 8000 bytes.** Larger payloads silently drop at the wire. Cross-worker mirrors must size-check client-side, log WARN, and keep local fan-out — degraded delivery beats raising on the publish path. Pin: `test_oversize_payload_is_dropped_locally_logged_no_crash`.
- **SQLAlchemy DSN ≠ asyncpg DSN.** Raw `asyncpg.connect()` rejects the `+asyncpg` suffix. Strip with `url.replace("postgresql+asyncpg://", "postgresql://", 1)` before opening LISTEN/NOTIFY connections.
- **Defensive `.get("task_id")` on `subscribe_all()` consumers.** Cross-worker fan-in amplifies any malformed event. Consumers should early-return on missing fields, not enforce schema — the listener is the wrong layer for that.

### SSE

- **`EventSourceResponse(content, ping=N)` is the keepalive knob.** Don't hand-roll periodic comment yields in the generator; the library emits the comment frame outside the user content stream.
- **SSE wire format uses CRLF; `\r` is invisible in diff output but breaks `showboat verify`'s byte-equality check.** Pipe SSE captures through `tr -d '\r'` before grep-ing for stable matches.
- **`showboat verify` re-runs every `exec` block in a clean shell.** Blocks must source `scripts/worktree-ports.sh` *inside* the captured command (not rely on surrounding script env), and must be idempotent (GET-then-POST or UPSERT — never assume a clean DB).

### Pin tests: presence vs absence

- **Presence-pins survive narrowing; absence-pins catch returns.** A presence-pin asserts a load-bearing rule is *recommended* (e.g. "this skill mentions `mcp__cloglog__search`") and survives codex narrowing the example list around it. Absence-pins catch the antipattern coming back. Use presence for "this guidance must remain"; absence for "this antipattern must not return". Don't conflate them — a presence-pin doesn't catch over-broadening.

### Cross-surface argument widening

- **Don't promote a brief's entity-type list verbatim into the documented argument grammar of an unrelated surface.** The set of entities a *resolver tool* accepts (e.g. `mcp__cloglog__search` accepts T-/F-/E-) is not the set a *workflow command* knows how to execute (e.g. `/cloglog launch` has no epic-launch path). Audit each surface against its own downstream code paths before widening accepted input.

### Plugin: MCP server registration

- **`.mcp.json` is the only file Claude Code loads project-scoped MCP servers from.** `.claude/settings.json.mcpServers` is silently ignored by Claude Code's MCP loader — `mcpServers` placed there will never start the server, `mcp__*` tools never resolve, and `/cloglog setup` fails with "register_agent doesn't exist". Any script or skill that thinks "merge this MCP block into settings.json" is broken-by-construction. Pin: `tests/plugins/test_init_on_fresh_repo.py::test_step3_block_writes_settings_with_no_placeholders`. Generalises beyond cloglog: any plugin that registers an MCP server for a downstream project must write to `.mcp.json` at repo root, not `.claude/settings.json`.
- **Config-migration: pop the specific subkey, not the parent map.** When moving config between files (e.g. T-344 hoisting `mcpServers.cloglog` from settings.json into `.mcp.json`), `settings.pop("mcpServers")` would silently delete every sibling entry an operator hand-maintained (`github`, `linear`, etc.). Pop only the migrated key and drop the parent only if it ends up empty. Generalises to any "consolidate config into one file" migration. Pin: `test_step3_migration_preserves_non_cloglog_mcp_servers`.

### Worktree env propagation

- **`/clear` between tasks ⇒ shell env any agent skill needs at runtime must be re-exported by `launch.sh`, NOT inherited from the operator's launching shell.** T-329 added per-task `/clear`; the supervisor relaunches via `bash launch.sh '<continuation>'` in the same zellij tab. While interactive zellij tabs preserve env across `bash` re-invocations on most hosts, "preserved" is host-specific (DE/login-shell/RC ordering) and silently flakes — agents that call `gh-app-token.py` exited with `Error: GH_APP_ID environment variable is required` mid-task on hosts where the RC export wasn't picked up by the zellij parent. T-348's fix is two-pronged: (a) `gh-app-token.py` resolves App ID/Installation ID itself from env → `.cloglog/local.yaml` → `.cloglog/config.yaml`, so non-worktree callers (close-wave, reconcile, init Step 6c) work without env priming; (b) `launch.sh`'s heredoc still exports them into worktree-agent shells so downstream `gh` calls that read the env directly keep working across `/clear`.
- **Operator-host bot identifiers must live in a gitignored file, not a tracked one.** App ID + Installation ID are non-secret but per-operator: each operator installs the App into their own org/repo and gets a distinct Installation ID. Committing them to `.cloglog/config.yaml` would push other clones at the wrong installation. The home is gitignored `.cloglog/local.yaml` (T-348). Tracked `.cloglog/config.yaml` remains a fallback only — sufficient for a single-operator repo, broken for any clone. The same constraint applies to any future per-operator value (PEM path overrides, host-specific webhook tunnel names already in config.yaml, etc.) — when in doubt, prefer `local.yaml`. Pin: `tests/plugins/test_launch_skill_exports_gh_app_env.py`.

### Plugin hooks: YAML parsing

- **`python3 -c 'import yaml'` in a plugin hook violates `docs/invariants.md:76`.** Multiple plugin entry points still inline `import yaml` to read `.cloglog/config.yaml`; on hosts without global PyYAML the worktree never registers, the scope guard drops, and unregister-by-path posts to the wrong backend. Mechanical grep+sed fix is fine for scalar-key parsers (pattern in `.cloglog/on-worktree-create.sh:88-105`), but **`protect-worktree-writes.sh` reads the nested `worktree_scopes` mapping** which grep+sed cannot represent — needs a plugin-shipped Python parser or a flatter config format. Don't call YAML-parser cleanup "mechanical" without checking each parser's nesting depth.
- **Client-side preflights vs. safety boundaries.** Hooks like `enforce-task-transitions.sh` look like guards, but the backend already blocks agent → `done` at `src/agent/services.py:417` and `:501`. Skipping such a hook is a UX/portability degradation, not a safety bypass. Audit findings about hooks must distinguish preflight UX from authoritative enforcement — codex catches the inversion.
- **Absence-pins on antipattern substrings collide with documentation that names the antipattern.** A naive pin asserting `"import yaml" not in body` blocks every comment/warning that *names* the antipattern in prose ("do NOT reintroduce `import yaml`"). Two ways out: (1) re-word warnings to a non-literal phrase ("the python YAML lib") and keep the pin trivial; (2) make the pin executable-form-aware (regex against `python3 -c "..."` blocks containing `import yaml`). Decide upfront whether the pin is on text or on executable code; (1) is simpler when feasible.
- **Generated `.cloglog/launch.sh` runs without `${CLAUDE_PLUGIN_ROOT}` — inline plugin helpers there, don't source.** Hook scripts at `plugins/cloglog/hooks/*.sh` resolve sibling `lib/*.sh` via `BASH_SOURCE`-relative paths because Claude Code invokes them from the plugin tree. The launch SKILL-emitted `.cloglog/launch.sh` is a standalone bash exec inside the worktree with no plugin tree on disk near it (the helper might live at `~/.claude/plugins/...` or any host-specific path). Inline a faithful copy of the helper's grep+sed shape into the template and pin the shape so drift is caught — sourcing across that boundary is brittle.
- **Templating shell into shell via unquoted heredoc multiplies escaping.** The launch SKILL emits `.cloglog/launch.sh` via `cat > ... << EOF` with an unquoted EOF: `${VAR}` expands at render time, `\$VAR` becomes `$VAR`, `\\` becomes `\`, `` \` `` becomes `` ` ``. Idioms like `tr -d '"'"'"'"'"'"''` survive shell-quoting in normal scripts but break inside the heredoc. Simplify the inner script to the dumbest unambiguous form (`tr -d '"' | tr -d "'"`) before adding heredoc-escape on top.
- **Migrating a permissive component to a strict one is a two-sided change — audit the callers.** When you swap a `try/except → []` parser for one that errors loudly, every `result=$(parser …) || exit 0` / `2>/dev/null` / `|| true` on the caller side that was a workaround for the *old* component's noise floor becomes a *silent bypass* against the new one. Audit checklist: for each error path the new component now signals, what does the caller do with it? If the answer isn't "block + log", the migration isn't complete. T-313 nearly shipped a `protect-worktree-writes.sh` that allowed every write because the inherited `|| exit 0` was preserved verbatim.

### Codex review on long-cycle PRs

- **Codex 5/5 cap is not an optional ceiling on factual-precision PRs.** Research/audit docs that cite file:line evidence burn codex sessions on every imprecision — each round generates new sibling findings as codex re-reads adjacent files. Bundling the entire scope correctly in round 1 is the only way to stay under the cap. Once exhausted, the PR is operator-driven; codex skips with a "request human review" comment.
- **`gitignored` ≠ "not a leak".** Audit findings should distinguish *tracked leak* from *host-specific runtime state* — gitignored files (e.g. `.cloglog/launch.sh`) can still embed operator-host absolute paths that break when copied between operators.
- **When operator direction overrides recommendations mid-review, preserve the original evidence trail.** Don't rewrite findings in place; strikethrough + Resolved annotation + a preamble carrying the override keeps the audit readable for downstream onboarding work.

### Inbox monitor

- **`agent_started` is the only authoritative liveness signal — supervisors must enforce a deadline.** A spawned zellij tab proves nothing about the claude session inside it (T-353 antisocial bug shipped a launch.sh with `unexpected EOF` and the supervisor never noticed; symptom was main stuck-waiting on review/merge events that would never arrive, with no `agent_started` event on the inbox). The main agent must wait up to `launch_confirm_timeout_seconds` (default 90s, in `.cloglog/config.yaml`) for `agent_started` per spawned worktree, then hand off to the operator with a `bash -n` / `query-tab-names` / `agent-shutdown-debug.log` / `.env` / `head -3 launch.sh` checklist. **Never silently retry** — every class of bootstrap failure (claude crash, heredoc render bug, half-applied `on-worktree-create.sh`, missing `.env`, MCP unavailable) has a different fix and the operator owns the call. Same deadline applies to supervisor relaunches between tasks. T-356.
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

### `gh pr merge` from a worktree

- **`gh pr merge --delete-branch` exits non-zero from a worktree where `main` is checked out by the parent clone, but the squash merge succeeds server-side.** The local post-merge cleanup (`git checkout main && git branch -D <branch>`) fails with `fatal: 'main' is already used by worktree at '<parent>'`, masking the successful merge. Don't panic on a non-zero exit — verify with the `pr_merged` inbox event or `gh pr view <num> --json state,mergedAt`. If you need clean post-merge state on the worktree side, do the ff-and-prune from the main clone, not as a side-effect of `gh pr merge`.
- **`Edit(replace_all=True)` on a SKILL.md silently breaks pin tests that count occurrences of *strings the SKILL.md references* — not occurrences of the SKILL filename.** Pins typically assert `body.count(literal) >= N` where `literal` is a path or token the SKILL.md cites. Example: `tests/plugins/test_auto_merge_skill_handles_silent_holds.py:42` pins `body.count("${CLAUDE_PLUGIN_ROOT}/scripts/auto_merge_gate.py") >= 2` against `plugins/cloglog/skills/github-bot/SKILL.md`'s body — the test names neither `github-bot` nor `SKILL`. Filename-based grep is the wrong heuristic and would have missed this exact pin. **Right grep before any `replace_all` on a SKILL.md:** (a) `body.count(` / `template.count(` / `\.count(` patterns in `tests/plugins/`, then verify whether each counted literal lives in the file you're about to edit; (b) the specific literal you're renaming (e.g. `auto_merge_gate.py`) — search every pin test for that string. Literal-based grep catches the actual pin; filename-based grep does not.
- **`.env` files are NOT auto-sourced by Claude agents or shell launchers.** A plugin script that needs `GH_APP_ID` / `GH_APP_INSTALLATION_ID` env vars cannot rely on a `.env` in the project root — bash subprocesses spawned by Claude inherit the parent shell's env, not the project's `.env`. Document the env-var contract as "set in `~/.bashrc` / `~/.zshenv` or via direnv with `.envrc`"; never imply a `.env` will work.
- **Pytest subprocess invocations needing extra packages: prefer `uv run --with <pkg>` over `sys.executable`.** When a test subprocess needs packages not in the test venv (e.g., `requests`, `PyJWT[crypto]`), `[sys.executable, str(script)]` resolves to `.venv/bin/python3` which lacks them and fails under `--cov=src`. Use `["uv", "run", "--with", "PyJWT[crypto]", "--with", "requests", "python", str(script)]` so dependencies are resolved at run time.

### Skills that touch GitHub

- **Every example command in a SKILL.md that touches GitHub must be bot-authenticated end-to-end** — `BOT_TOKEN=$(...)`, `git remote set-url origin "https://x-access-token:${BOT_TOKEN}@..."`, `git push -u origin HEAD`, `GH_TOKEN="$BOT_TOKEN" gh ...`. Saying "use the github-bot skill's flow" in prose is not enough; readers copy the command they see, not the prose around it. Pin tests should assert the bot-authenticated form is *present* (positive substring), not just the unauthenticated form is absent.
- **Pin tests asserting absence still apply when the pattern was already paraphrased away.** If a spec asks you to retire pattern X and X isn't a literal string in the file today, still write the pin test. Workarounds rot integration flows quietly; only absence-asserts catch a future revert. Pinning a string that doesn't currently appear is the entire point — not redundant.

### Auto-merge / PR gates

- **`gh pr view --json statusCheckRollup` has no `bucket` field.** That normalized enum exists only on `gh pr checks --json name,bucket`. `gh pr view` returns `conclusion`/`status` enums in CheckRun shape. `gh pr view` also rejects `--arg` (that flag is `gh api` / standalone `jq` only). Run any documented executable command sequence end-to-end before merging the docs that describe it.
- **`paths:` filter in `.github/workflows/ci.yml` produces empty `statusCheckRollup` on docs-only PRs.** Any auto-merge gate that treats "empty checks list" as "still pending" will deadlock those PRs. The semantically right answer is "no CI signal to wait for ⇒ green" (codex still ran; spec PRs are docs-only by intent).
- **Codex's `event="COMMENT"` is a body marker, not a GitHub approval.** A human `CHANGES_REQUESTED` review still blocks merge. Any auto-merge gate must fetch `gh api repos/.../pulls/<n>/reviews`, filter to non-bot users, group by login, take the latest review per author, and refuse the merge if any latest is `CHANGES_REQUESTED` — user-block fires before label/CI checks.

### Backwards-compat for documented contracts

- **When replacing a documented runtime contract, retire it end-to-end or chain a fallback.** Tests passing on the new path doesn't catch operators who set the old setting per the still-current `.env.example`. Either delete the setting + update docs in the same PR, or keep the old path as a fallback. Don't leave docs claiming behavior the code no longer provides.

### Board / task repository

- **`update_task` repository applies all fields unconditionally — `if value is not None` was wrong for fields declared on `TaskUpdate`.** The route layer uses `exclude_unset=True`, so only fields the caller explicitly included arrive at the repository; the old guard was double-filtering and prevented explicit `null` from clearing nullable columns. If you add a nullable field to `Task` and find it can't be cleared via PATCH: (1) ensure the field is declared on `TaskUpdate` (otherwise `model_dump(exclude_unset=True)` will never forward it regardless), then (2) check for a residual `if value is not None` guard in `repository.py`. Both changes are required — removing only the repository guard for a field not on `TaskUpdate` has no effect.

### Demo classifier / exemption gate (F-51)

- **Allowlist regexes must be validated against the actual repo path tree.** Grep every path class before writing — a narrow-by-accident regex blocks the feature it enables (e.g., `plugins/*/hooks/` broke rollout PRs that touch `plugins/cloglog/skills/`; nested `package-lock.json` lives at `frontend/` and `mcp-server/`, not root).
- **Route rules: key on the decorator, not the filename.** When a subagent rule says "user-observable HTTP routes," match `@[A-Za-z_]*router\.(get|post|patch|put|delete)\(` across all bounded contexts — not `src/gateway/**/routes.py`.
- **Test fixtures that shortcut the production flow can hide the exact failure mode you care about.** Writing `exemption.md` untracked covers the happy path but misses self-invalidation: committing the file changes the diff bytes, changing the SHA256, invalidating the stored `diff_hash`. Pin tests should reflect the real agent flow, not a convenient untracked-file shortcut.
- **Two-dot vs three-dot `git diff` matters for diff_hash correctness.** `git diff A B` (two-dot) includes changes A has that B doesn't; `git diff A...B` (three-dot) is merge-base-to-B. When `A` is a resolved merge-base SHA both produce identical bytes; when `A` is a raw ref and main has advanced, two-dot includes main's new commits as "removed." Use three-dot in the classifier; document equivalence conditions explicitly at every hash-computation site.
- **Codex's 5-session cap is a hard ceiling; bundle the full scope correctly in round 1.** When a PR generates round-after-round of sibling-file findings the scope is still expanding — include every affected file before the first codex turn, or expect to hit the cap without approval.
- **Exemption hash must be recomputed after every commit round.** The classifier pins the exemption to `sha256` over `git diff "$MERGE_BASE" HEAD -- . ':(exclude)docs/demos/'`. The pathspec exclude keeps the hash bound to *code* changes, not the exemption file itself — but every new commit on the branch (codex-fix round, ruff fix, lint round) shifts the diff and invalidates the stored `diff_hash`. Refresh `docs/demos/<wt>/exemption.md`'s `diff_hash` after every commit round, or the next `make quality` run rejects the PR. T-329 hit this five times across codex sessions before the agent learned to refresh in lockstep.
