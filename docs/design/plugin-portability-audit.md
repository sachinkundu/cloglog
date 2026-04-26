# Plugin Portability Audit (T-307)

**Status:** research / design — no implementation in this PR.
**Scope:** identify every place the cloglog plugin (`plugins/cloglog/`) and the
machinery it ships against (`mcp-server/`, `.cloglog/`, `scripts/`, root docs)
is implicitly bound to the cloglog repo itself, when the product premise is
that `/cloglog init` should onboard *any* project.

The product premise is that the **plugin** is the reusable surface and the
cloglog repo is just its first dogfood project. In practice we have built and
exercised the plugin only against this one repo; the audit below catalogues
every leak that surfaces the moment a second project tries to install it.

## Executive summary — top 5 friction points

Ranked by adoption blast radius. Each blocks `/cloglog init` from producing a
working multi-agent project on a fresh repo, end-to-end.

1. **`/cloglog init` has no installation step.** The skill assumes
   `plugins/cloglog/`, `scripts/gh-app-token.py`, `scripts/wait_for_agent_unregistered.py`,
   `scripts/install-dev-hooks.sh`, the entire MCP server (`mcp-server/`), the
   prod-promote tooling (`make promote`, `make verify-prod-protection`), the
   webhook tunnel (`cloglog-webhooks` cloudflared), and the cloglog backend
   itself are all *already present* in the project being initialized. There is
   no story for "get a fresh repo to the point where `/cloglog init` is
   runnable." Net: today the plugin only works inside the cloglog repo and
   any sibling clone of it.
2. **Hardcoded reviewer-bot login, dashboard key, and tunnel name in the
   plugin.** `cloglog-codex-reviewer[bot]` (auto-merge gate, github-bot
   skill), `cloglog-opencode-reviewer[bot]` (review_engine), the
   `cloglog-dashboard-dev` X-Dashboard-Key (demo skill examples), the
   `cloglog-webhooks` cloudflared tunnel name (preflight), and the `cloglog`
   /`cloglog_dev` Postgres role/password (worktree-infra) all bake the cloglog
   org into shared code. A second project would have to fork the plugin to
   change them.
3. **Skills cite cloglog source paths as authoritative.** The setup, launch,
   github-bot, close-wave, reconcile, and demo skills, plus the worktree-agent
   prompt and `claude-md-fragment.md`, reference `src/agent/services.py:357-370`,
   `src/gateway/webhook_consumers.py`, `src/gateway/review_engine.py`,
   `src/board/templates.py:24-25`, etc. — line numbers and module paths from
   *this* backend. On a non-DDD or non-FastAPI project those citations are
   noise at best, instructions to read code that doesn't exist at worst.
4. **`.cloglog/` runtime artifacts are not portable today.** The dogfood
   `.cloglog/config.yaml` ships repo-specific
   `worktree_scopes` keyed to `src/board/`, `src/agent/`, `src/document/`,
   `src/gateway/`, `frontend/`, `mcp-server/` (the `protect-worktree-writes`
   hook would block every write on a project with a different layout until
   the operator authors a config from scratch). `.cloglog/launch.sh` is
   regenerated per-worktree by the launch skill but the **example committed
   in this repo** has absolute `/home/sachin/code/cloglog/...` paths
   embedded (`launch.sh:3-4`), and `.cloglog/on-worktree-create.sh` calls
   `${REPO_ROOT}/scripts/worktree-infra.sh` (a cloglog-only file) and
   `curl /api/v1/agents/close-off-task` against a backend that may not be
   running. The init skill emits scaffolding for `on-worktree-create.sh`
   based on `pyproject.toml`/`package.json`/`Cargo.toml`, but the result is
   `uv sync` / `npm install` only — none of the agent-vm port allocation,
   per-worktree Postgres, or close-off-task plumbing that a real cloglog
   project depends on for `/cloglog launch` to work.
5. **GitHub App identity is single-tenant by design.** Both reviewer Apps and
   the cloglog-bot App are addressed by name in `src/gateway/github_token.py`
   (`_OPENCODE_APP_ID`, `_OPENCODE_INSTALLATION_ID`), `scripts/gh-app-token.py`
   is project-checked-in (init copies it from `~/code/*` if found — a fragile
   global filesystem search), and PEMs live in `~/.agent-vm/credentials/<bot>.pem`
   with hardcoded names (`codex-reviewer.pem`, `opencode-reviewer.pem`,
   `github-app.pem`). A second project either reuses this exact App (cross-org
   permissions issues) or stands up its own and has to fork the
   `_OPENCODE_*` constants. Neither story is documented anywhere.

## Findings by category

Citations are `file:line` against this worktree (HEAD of
`wt-t307-plugin-portability-audit`).

### 1. Plugin code (`plugins/cloglog/`)

| File:line | What's hardcoded | Impact on new project | Proposed fix |
|---|---|---|---|
| `plugins/cloglog/.claude-plugin/plugin.json:2-3` | name `cloglog`, description `cloglog-managed projects` | Cosmetic; reads as a cloglog-specific tool | Reframe description as project-agnostic ("multi-agent kanban workflow") |
| `plugins/cloglog/.claude-plugin/marketplace.json:2,8-9` | Marketplace name `cloglog-dev` | Reads as one-org marketplace | OK if intent is single-source; otherwise rename `cloglog-marketplace` |
| `plugins/cloglog/skills/init/SKILL.md:43,387` | Default `backend_url: http://localhost:8000`; "Start the cloglog backend if not running" | Implies one backend per host. On a host that already runs the cloglog backend on :8000, a second project's MCP server collides | Document that backend is *one shared service* across projects; the project_id discriminates rows. Otherwise document port-per-project setup |
| `plugins/cloglog/skills/init/SKILL.md:62-77` | MCP server entry uses `"args": ["/path/to/mcp-server/dist/index.js"]` placeholder; SessionStart hook uses `<absolute-path-to-project>/plugins/cloglog/hooks/session-bootstrap.sh` | Placeholder — init never actually resolves these paths. Operator gets a settings.json with literal `/path/to/mcp-server/dist/index.js` and `<absolute-path-to-project>` markers | Generate concrete paths at init time using `${CLAUDE_PLUGIN_ROOT}` for the hook (acknowledged not to resolve) — or copy the bootstrap into the project as part of init |
| `plugins/cloglog/skills/init/SKILL.md:209-223` | "Look for `~/.agent-vm/credentials/github-app.pem` on disk" + `find ~/code -path "*/scripts/gh-app-token.py"` | Searches the operator's whole `~/code` tree for a script. Brittle, surprising, and silently no-ops if user keeps repos elsewhere | Vendor `gh-app-token.py` as a plugin-shipped script (`plugins/cloglog/scripts/gh-app-token.py`) so init copies from a known location |
| `plugins/cloglog/skills/init/SKILL.md:234` | `Name: something like "cloglog-bot"` | Suggests every project name its bot after cloglog | Rename guidance to `<project>-bot` |
| `plugins/cloglog/skills/init/SKILL.md:288-310` | Tech-stack detection adds Python/FastAPI, React, Node, Rust, DDD review-prompt fragments | Fine in principle but the FastAPI/DDD branches were written *for cloglog* — they're not exercised against any other project | Extract per-stack fragments to `plugins/cloglog/templates/review-fragments/<stack>.md` and pin them with at least one fresh-repo test |
| `plugins/cloglog/skills/setup/SKILL.md:51,56,60` | "see `src/gateway/webhook_consumers.py`", "`src/agent/services.py:357-370`", "`tests/agent/test_unit.py:1253-1357`", "`scripts/wait_for_agent_unregistered.py`" | Citations are to cloglog source. Non-cloglog readers will follow the link and find nothing | Refactor citations to *behavioral contracts* ("the inbox is append-only for the worktree's lifetime") with the cloglog-source pointer as a parenthetical, or move citations to a "cloglog-specific notes" appendix |
| `plugins/cloglog/skills/launch/SKILL.md:88,98-99,154` | Same pattern: cites `src/gateway/webhook_consumers.py`, `src/agent/services.py:237`, `src/agent/services.py:357-370`, `docs/design/agent-lifecycle.md` §4.1 | Same as above. `docs/design/agent-lifecycle.md` is *also* cloglog-only (the file lives in this repo, not in the plugin) | Move `docs/design/agent-lifecycle.md` into `plugins/cloglog/docs/agent-lifecycle.md` so it ships with the plugin |
| `plugins/cloglog/skills/launch/SKILL.md:154` + `plugins/cloglog/agents/worktree-agent.md:55` + `plugins/cloglog/templates/claude-md-fragment.md:32` | "Backend gap T-NEW-b: `src/agent/services.py:237`" | Three places hardcode the same line number plus a TODO ID against the cloglog backend. Bit-rot risk even within cloglog; broken on any other project | Either land T-NEW-b and delete the workaround, or factor the workaround into a single skill section the others link to |
| `plugins/cloglog/skills/github-bot/SKILL.md:13,19,59,117,194,231,267,315,332` | Every example: `BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)` | Hardcodes `scripts/gh-app-token.py` (project-checked-in) and `uv` toolchain. A non-uv project copying this verbatim hits "uv: command not found" | Vendor the script + provide a `${CLAUDE_PLUGIN_ROOT}/scripts/gh-app-token.py` resolver; document the `uv` requirement explicitly under "Prerequisites" |
| `plugins/cloglog/skills/github-bot/SKILL.md:185` | `Reviewer is "cloglog-codex-reviewer[bot]"` (auto-merge gate matches the login literally) | A second project's reviewer App will never satisfy the gate | Read the reviewer login from `.cloglog/config.yaml` (`reviewer_bot_logins: [...]`) |
| `plugins/cloglog/skills/github-bot/SKILL.md:231,267` | `python3 plugins/cloglog/scripts/auto_merge_gate.py` (relative path) | Works only when CWD is the project root and the plugin is checked in at that path | Resolve via `${CLAUDE_PLUGIN_ROOT}/scripts/auto_merge_gate.py` |
| `plugins/cloglog/skills/close-wave/SKILL.md:82` | `(e.g., \`../cloglog-prod\` is the prod worktree — never touch it)` | Bakes the cloglog dev/prod sibling-clone topology into the close-wave guard | Read `prod_worktree_path` from `.cloglog/config.yaml` (it's already there: `.cloglog/config.yaml:4`); remove the literal `cloglog-prod` from prose |
| `plugins/cloglog/skills/close-wave/SKILL.md:99,253,340` | `BOT_TOKEN=$(uv run … scripts/gh-app-token.py)` | Same as github-bot | Same fix |
| `plugins/cloglog/skills/close-wave/SKILL.md:169,302,360` | `uv run python scripts/wait_for_agent_unregistered.py …`; `scripts/install-dev-hooks.sh` | Two cloglog-only scripts referenced as if they ship with every project | Vendor both into `plugins/cloglog/scripts/` |
| `plugins/cloglog/skills/reconcile/SKILL.md:131,143,263,286` | Same `gh-app-token.py`, `wait_for_agent_unregistered.py`, `install-dev-hooks.sh` references | Same | Same |
| `plugins/cloglog/skills/reconcile/SKILL.md:171,178,182,186` | Cites `src/board/services.py::create_close_off_task`, `src/board/schemas.py::TaskResponse`, `src/board/templates.py:20`, `src/board/templates.py:24-25` | Backend layout assumed | Same as setup-skill remediation: contract-style + appendix |
| `plugins/cloglog/skills/demo/SKILL.md:40` + `scripts/check-demo.sh:31` | Allowlist regex hardcodes `plugins/[^/]+/(hooks\|skills\|agents\|templates)/` and the cloglog-shaped paths (`src/`, `frontend/src/`, `mcp-server/src/`, etc.) | Allowlist matches *cloglog's* infra paths. A non-cloglog project loses Step 0 short-circuiting and hits the classifier on every PR | Make the allowlist read from `.cloglog/config.yaml` (`demo_allowlist_paths: [...]`) with the current set as the default |
| `plugins/cloglog/skills/demo/SKILL.md:242,248,255,264` | `X-Dashboard-Key: cloglog-dashboard-dev` curl examples | Two-fold leak: (a) cloglog-specific dashboard key; (b) implies every project shares the same auth header | Replace with a placeholder/`${DASHBOARD_KEY}` env var; document where the key comes from |
| `plugins/cloglog/skills/demo/SKILL.md:279` | "`tests/conftest.py` has a session-autouse fixture that opens a PostgreSQL connection" | cloglog's conftest behavior elevated to general advice | Move to a "cloglog-specific notes" footnote |
| `plugins/cloglog/skills/demo/SKILL.md:422` | `grep -c "\-\-dangerously-bypass" src/gateway/review_engine.py` example | cloglog-source example | Replace example with a generic one |
| `plugins/cloglog/agents/worktree-agent.md:29,55` | "run whatever the project's CLAUDE.md defines (e.g., `make quality`)" + the T-NEW-b workaround block citing `src/agent/services.py:237` | First case is fine (acknowledges variation); second case is repo-specific | Delete T-NEW-b once landed; otherwise move workaround to a single shared skill section |
| `plugins/cloglog/templates/claude-md-fragment.md:14` | "matches what `plugins/cloglog/skills/github-bot` and `plugins/cloglog/agents/worktree-agent.md` require" | Internal cross-references inside the injected fragment leak the plugin's own filesystem layout into the project's CLAUDE.md | Drop the file references; document the contract directly |
| `plugins/cloglog/templates/claude-md-fragment.md:32` | Same T-NEW-b citation | Same |
| `plugins/cloglog/templates/codex-review-prompt.md:61-63` | Route decorator regex assumes routers in `src/**`; component regex assumes `frontend/src/**` | Codex review prompt won't trigger on projects with different layouts | Make the regex paths configurable, or generate the prompt per-project (init Step 7 already partly does this) |
| `plugins/cloglog/templates/codex-review-prompt.md:61` (cont.) | Enumerates `src/board/routes.py`, `src/agent/routes.py`, `src/document/routes.py`, `src/gateway/routes.py`, `src/gateway/sse.py`, `src/gateway/webhook.py` by name | Cloglog DDD layout enumerated literally | Replace with route-decorator regex only; drop the enumeration |
| `plugins/cloglog/scripts/auto_merge_gate.py:11,14,107` | Cites `src/gateway/review_engine.py` and `src/**`/`frontend/src/**`/`mcp-server/src/**`/`tests/**` allowlist | Hardcoded source-tree assumptions inside the gate script | Read allowlist from config; use the same `demo_allowlist_paths` proposal as above |
| `plugins/cloglog/hooks/protect-worktree-writes.sh:3,32-42` | Hook reads `worktree_scopes` from `.cloglog/config.yaml` (good) — but **cloglog's** config.yaml ships scopes keyed to `src/board/`, `src/agent/`, `src/document/`, `src/gateway/`, `frontend/`, `mcp-server/`, `assign`, `e2e` (`.cloglog/config.yaml:7-15`) | A new project must hand-author scopes for its own layout. `/cloglog init` does *not* generate this section, so a fresh project starts with no scope guard at all | Either (a) generate a permissive default scope from the tech stack, or (b) make the hook a no-op when no `worktree_scopes` key is present and document that explicitly |
| `plugins/cloglog/hooks/quality-gate.sh:42-43` | Falls back to `make quality` if config is missing | Reasonable default but invisible to a project that uses `npm test` and forgets to set `quality_command:` | Make the fallback an error ("no quality_command in .cloglog/config.yaml") rather than silently running a missing make target |
| `plugins/cloglog/hooks/session-bootstrap.sh:5-8` | Reads `git rev-parse --abbrev-ref HEAD` and skips when branch matches `wt-*` | Hardcodes the cloglog worktree-branch convention | Read worktree-branch prefix from config (default `wt-`) |
| `plugins/cloglog/settings.json:86` | Hook matcher `mcp__cloglog__update_task_status\|mcp__cloglog__complete_task` | The plugin name is on the wire as MCP server name `cloglog`, so this is correctly stable across projects — but it does mean the *MCP server name* itself is a single-tenant identifier (see #2 below) |  Document |

### 2. MCP server (`mcp-server/src/`)

The MCP server is *correctly* written to be project-agnostic at the data layer
(every read/write is project-scoped via the project API key). The leaks are
naming and credential-resolution.

| File:line | What | Impact | Proposed fix |
|---|---|---|---|
| `mcp-server/src/index.ts:14` | `MCP_SERVICE_KEY = process.env.MCP_SERVICE_KEY ?? 'cloglog-mcp-dev'` | Default service key bakes "cloglog" into the dev fallback; if a deployer relies on the default, the cloglog backend will accept it but a non-cloglog backend may not have that key seeded | Default to env-required (no fallback); error out at startup if missing |
| `mcp-server/src/index.ts:4,37` + `mcp-server/src/server.ts:39` | Server name `cloglog-mcp` | The MCP `name` field is what shows up in `.mcp.json` and the agent's tool list (`mcp__cloglog__*`). Renaming would break every existing skill that greps for `mcp__cloglog__`. Trade-off: keep "cloglog" as the brand or add an alias layer | Keep — the rename cost is enormous, and the brand is reasonable for "the kanban-orchestration plugin" |
| `mcp-server/src/credentials.ts:20,108` | Credentials path defaults to `~/.cloglog/credentials`; warning string `cloglog-mcp` | Cosmetic — the path is a brand choice and the warning prefix is fine | Keep |
| `mcp-server/src/server.ts:88,260,289` | Tool descriptions reference cloglog ("Register this worktree with cloglog", "called by `.cloglog/on-worktree-create.sh`") | Tool descriptions surface to agents; "cloglog" leaks into the tool listing | Acceptable if "cloglog" is the chosen brand for the system |
| `mcp-server/src/errors.ts:24-25,2` + `mcp-server/src/client.ts:2` | Error class prefix `cloglog API error: …`; module docstring says "cloglog API" | Cosmetic | Same — keep brand |

Net: the MCP server is portable in behavior; what's not portable is anything
that names "cloglog" in error/help text, which is a rebrand decision rather
than a functional gap.

### 3. Backend (`src/*`) — out of audit scope by request

The audit prompt explicitly notes that the backend Project model already
supports multi-project. Spot-checks confirm no per-project hardcoded names in
data flow. The leak surface that matters here is in adjacent infra:

| File:line | What | Impact | Proposed fix |
|---|---|---|---|
| `scripts/worktree-infra.sh:20-21` | `PG_USER="${PG_USER:-cloglog}"`, `PG_PASSWORD="${PG_PASSWORD:-cloglog_dev}"` | Per-worktree Postgres falls back to cloglog credentials | Read from project config; if absent, error out with a clear message |
| `scripts/worktree-ports.sh:20,23-24` | DB name template `cloglog_${WORKTREE_NAME//-/_}`; same PG defaults | Worktree DB names hardcode cloglog brand | Use project name as the DB-name prefix |
| `scripts/preflight.sh:73-74` | Recommends `cloudflared tunnel run cloglog-webhooks` | Tells operator to start a tunnel they don't have | Read tunnel name from config; or skip preflight on projects that don't ship webhooks |
| `scripts/preflight.sh:74` (cont.) | Tunnel name `cloglog-webhooks` and host `cloglog.voxdez.com` (Makefile:177,218) | Single-tenant tunnel | Tunnel-per-project; document where to point GitHub webhooks for project N |
| `scripts/gh-app-token.py:2` | "Generate a GitHub App installation token for cloglog-agent" + hardcoded App ID / Installation ID inside the script | One App per cloglog deployment | Vendor a templated version into `plugins/cloglog/scripts/`; init renders it with project-specific App/Installation IDs |
| `Makefile` (entire file) | All `make prod`/`make promote`/`make verify-prod-protection` targets assume `../cloglog-prod` sibling, port 8001, `/tmp/cloglog-prod*.pid`, `cloglog.voxdez.com` host | Cloglog-only by design | Out of scope — this is the cloglog **deployment** Makefile, not the plugin. Document explicitly that `make prod` is cloglog-only |
| `docs/design/prod-branch-tracking.md` (whole file) | Documents the cloglog-specific dev/prod twin-clone topology | Reads as plugin docs but is cloglog-deployment specific | Move out of plugin's referenced doc set; keep as cloglog-internal design |

### 4. `.cloglog/` runtime (this repo's working state)

What exists today vs. what `/cloglog init` would generate on a fresh repo:

| File | This repo (cloglog) | Init output (fresh repo) | Gap |
|---|---|---|---|
| `config.yaml` | `project: cloglog`, `project_id: <uuid>`, `backend_url: http://127.0.0.1:8001`, `prod_worktree_path: ../cloglog-prod`, `quality_command: make quality`, `worktree_scopes: {board, agent, document, gateway, frontend, mcp, assign, e2e}` | `project_name`, `backend_url`, `quality_command` only (no `project_id`, no `prod_worktree_path`, no `worktree_scopes`) | Init does not produce the scopes the protect-worktree-writes hook needs; `project_id` is also absent — agent registration succeeds because the backend resolves project by API key, but skills that read `project_id` from config (e.g., `scripts/sync_mcp_dist.py:151`) would fail |
| `on-worktree-create.sh` | 145 lines: shutdown-artifacts reset, `worktree-infra.sh up`, `uv sync --extra dev`, frontend install conditional on `wt-frontend*`, `mcp-server` install conditional on `mcp-server/package.json`, close-off-task POST to backend with project API key, env-driven `_resolve_backend_url`/`_resolve_api_key` helpers | Init produces ~5 lines: `cd $WORKTREE_PATH; uv sync` (or `npm install`, etc.) | Init's output is correct as a *minimal* setup but does not file the close-off task or stand up per-worktree Postgres / port allocation. Multi-worktree projects without these would collide on a single dev DB |
| `on-worktree-destroy.sh` | Calls `worktree-infra.sh down` | Init produces an empty stub | Same gap |
| `launch.sh` | Auto-generated by launch skill per worktree; the example committed in the audit branch has `WORKTREE_PATH="/home/sachin/code/cloglog/.claude/worktrees/wt-t307-plugin-portability-audit"` and `PROJECT_ROOT="/home/sachin/code/cloglog"` (lines 3-4) | Skill generates per-worktree at launch time | The committed example **must not be checked in** — it freezes the operator's home path. Add `.cloglog/launch.sh` to `.gitignore`. (Possible existing bug in this very PR; verify in step 9.) |
| `inbox` | Runtime state, gitignored (`init` Step 8 adds it) | Same | OK |

### 5. Skills — additional cross-cutting issues

Beyond the per-skill citations in §1, two systemic patterns:

- **Skills assume `pwd` is the project root.** `plugins/cloglog/hooks/session-bootstrap.sh:11` uses `PROJECT_DIR=$(pwd)`. The setup skill repeatedly says `<current working directory>` in place of `$PROJECT_ROOT`. This works for the common case (operator launches Claude from the project root) but breaks on cd-into-subdir starts, including the Bash-tool's persistent CWD model. Consider deriving project root from `git rev-parse --show-toplevel` consistently. (`plugins/cloglog/skills/close-wave/SKILL.md:144` and `plugins/cloglog/skills/reconcile/SKILL.md:32` already do this — make it the universal pattern.)
- **Skills cite `<project_root>/.cloglog/inbox` versus `<worktree_path>/.cloglog/inbox` inconsistently in prose.** The contract is correct (main inbox lives at project root; per-worktree inbox lives in the worktree) but readers confuse the two on first read. Add a single "Inbox locations" sub-section in `claude-md-fragment.md` or a top-level skills/README that the others link to.

### 6. `/cloglog init` walkthrough on a fresh repo

I created `/tmp/audit-fresh-repo` (`git init` + a one-line README) and walked
through the steps that `plugins/cloglog/skills/init/SKILL.md` would execute,
*without running them* — running them requires the plugin to already be
installed in the fresh repo, and that's the first gap.

| Step | What init does | What happens on fresh repo |
|---|---|---|
| 0 (missing) | Install the plugin into the project | **Step 0 does not exist.** The skill assumes `plugins/cloglog/` is already vendored at `<project>/plugins/cloglog/`. There is no `git submodule add`, no `claude-marketplace install`, no copy step. A fresh repo has no plugin at all and therefore cannot invoke `/cloglog init` |
| 1a | Detect project name from `basename $(pwd)` | Works |
| 1b | Detect quality command (Makefile/package.json/Cargo/pyproject) | Works for the four detected stacks; fails closed for anything else (asks user) |
| 1c | Default backend_url `http://localhost:8000` | Works *if* the operator already runs the cloglog backend. Otherwise the rest of the flow succeeds, but the agent will fail at first MCP call |
| 2 | Call `mcp__cloglog__get_board` to check project exists | **Cannot run before MCP is configured (Step 3).** Step 2 is out of order — at step 2 the MCP server has not been configured for this project, and the project API key is not yet in `~/.cloglog/credentials`. The MCP tool will not be loaded. The skill papers over this with "the user will need to register it through the backend API or MCP tools" — i.e., manual |
| 3 | Inject `cloglog` MCP server into `.claude/settings.json` with placeholder `"args": ["/path/to/mcp-server/dist/index.js"]` | The placeholder is **literal**. The skill never asks the operator where their MCP server build lives. On first session restart the MCP server fails to start, the agent has no `mcp__cloglog__*` tools, and the SessionStart hook prints "Run /cloglog setup" — which then fails the same way |
| 4a | Write `.cloglog/config.yaml` with project_name/backend_url/quality_command | Misses `project_id`, `worktree_scopes`, `prod_worktree_path`. See gap in §4 |
| 4b | Write `on-worktree-create.sh` for detected stack | Generates a minimal `uv sync` / `npm install` script with no infra setup. `/cloglog launch` later fails when it tries to call `mcp__cloglog__create_close_off_task` because the hook never fires it |
| 4c | Write `on-worktree-destroy.sh` (empty stub) | Works |
| 5 | Append "Workflow Discipline (cloglog)" section to CLAUDE.md | Works. **Side effect**: rules block agents from working on tasks before the board exists; the project must register itself first via Step 2, which it can't do (see above) |
| 6a | Check for `git remote get-url origin` | Works. Fresh repo has no remote → records "GitHub repo: not configured" and continues |
| 6b | Look for `~/.agent-vm/credentials/github-app.pem` and `find ~/code -path "*/scripts/gh-app-token.py"` | Brittle. On a host with no `~/code/` checkout, the find returns nothing and the bot setup is skipped silently |
| 6c | If both exist, verify bot has access | Works |
| 7a | Generate codex review prompt and copy schema. The skill says `PLUGIN_ROOT="<path to plugins/cloglog>"` — **literal placeholder** | Placeholder. The script block requires the operator to fill it in. No agent could automate this from prose |
| 7b | Append `## Review guidelines` to AGENTS.md/CLAUDE.md | Works |
| 7c | Symlink AGENTS.md ↔ CLAUDE.md | Works |
| 8 | `echo '.cloglog/inbox' >> .gitignore`, then `git add .cloglog/ .github/codex/ .gitignore` | Works |
| 9 | Print summary, remind operator to set `~/.cloglog/credentials` | Works as text, but every preceding step that landed a placeholder (`/path/to/mcp-server/dist/index.js`, `<absolute-path-to-project>`, `<path to plugins/cloglog>`) is now committed to the project |

**Net assessment:** `/cloglog init` cannot today produce a working multi-agent
project on a fresh repo. The minimum changes to make it work are: (a) a
prerequisite step that vendors the plugin and the MCP server, (b) resolution
of all `<...>` placeholders to concrete paths, (c) generation of
`worktree_scopes` and `project_id`, (d) a generated `on-worktree-create.sh`
that registers a close-off task, and (e) a documented bot-setup story that
doesn't depend on the operator having a sibling cloglog clone in
`~/code/`.

### 7. Documentation

| File | Cloglog assumption | Proposed fix |
|---|---|---|
| `docs/setup-credentials.md` (whole file) | Documents `~/.cloglog/credentials`, `~/.agent-vm/credentials/<bot>.pem`, hardcoded reviewer App constants | Move to `plugins/cloglog/docs/setup-credentials.md` so it ships with the plugin; reference reviewer Apps as templates |
| `docs/design/agent-lifecycle.md` (whole file) | Authoritative spec for the lifecycle, lives in cloglog repo only | Move to `plugins/cloglog/docs/agent-lifecycle.md` |
| `docs/design/two-stage-pr-review.md` | Cloglog reviewer-bot architecture (codex + opencode) | Same — move into plugin docs |
| `docs/design/prod-branch-tracking.md` | Cloglog dev/prod twin-clone topology | Stays in cloglog (deployment-specific) |
| `docs/invariants.md` | Cloglog-specific silent-failure invariants | Stays in cloglog (project-specific) but split out the few that are plugin contract (e.g., `.cloglog/config.yaml` parsing) into the plugin |
| `README.md` | (not audited in detail; read-only spot check) | Document plugin install path |

### 8. Tests — pin tests for plugin behaviour against non-cloglog projects

Suspected zero. Confirmed: a grep of `tests/` for `portab|generic|fresh` returns no results.

| Gap | Proposed fix |
|---|---|
| No fresh-repo `/cloglog init` smoke test | Add `tests/plugin/test_init_on_fresh_repo.py` that creates a `tmp_path` repo, runs the init steps non-interactively, and asserts every generated artifact has no `<...>` placeholders and no `cloglog` literals |
| No portability assertion that skills don't grow new cloglog citations | Add a pin test that greps `plugins/cloglog/` for the strings catalogued above and fails on regressions (echoing the existing pattern from `tests/test_mcp_json_no_secret.py`) |

### 9. Webhook + GitHub App — multi-tenancy

Today's model:
- One cloudflared tunnel (`cloglog-webhooks`, `cloglog.voxdez.com`) → one
  cloglog backend → routes by `X-Hub-Signature-256` matching one
  webhook secret per repo.
- One supervisor App (`cloglog-bot`) per cloglog deployment, App ID and
  Installation ID baked into `scripts/gh-app-token.py`.
- Two reviewer Apps (`cloglog-codex-reviewer[bot]`,
  `cloglog-opencode-reviewer[bot]`) with App IDs/Installation IDs hardcoded
  in `src/gateway/github_token.py`.

Friction for project N:
- N either reuses cloglog's three Apps (cross-org `Repository access`
  configuration; cloglog org admin must approve each install) or stands up
  its own three Apps and forks `github_token.py` constants. Neither path
  has a doc.
- N's webhook traffic must reach cloglog's tunnel (`cloglog.voxdez.com`) or
  N must run its own backend behind its own tunnel. The plugin assumes the
  former without saying so.
- The reviewer-bot login (`cloglog-codex-reviewer[bot]`) is matched
  literally in the auto-merge gate — N can't swap to a different reviewer
  identity without code changes.

## Recommended sequence

Phase 1 — **make the plugin self-contained** (no behavior change for cloglog):

1. Vendor cloglog-only scripts the plugin already references into
   `plugins/cloglog/scripts/`: `gh-app-token.py`, `wait_for_agent_unregistered.py`,
   `install-dev-hooks.sh`, `auto_merge_gate.py` (already there). Update
   skill examples to use `${CLAUDE_PLUGIN_ROOT}/scripts/...`.
2. Move `docs/setup-credentials.md`, `docs/design/agent-lifecycle.md`,
   `docs/design/two-stage-pr-review.md` into `plugins/cloglog/docs/`. Update
   citations.
3. Replace literal hardcoded values in skills/scripts with config.yaml keys:
   `reviewer_bot_logins`, `dashboard_key`, `webhook_tunnel_name`,
   `prod_worktree_path` (already in config — just stop hardcoding it in
   prose), `demo_allowlist_paths`.
4. Add `.cloglog/launch.sh` to `.gitignore` (it's auto-generated; the
   committed copy in this audit-branch worktree shows the leak).

Phase 2 — **make `/cloglog init` actually work on a fresh repo**:

5. Add a Step 0 that vendors the plugin (decision: submodule vs. plugin
   marketplace vs. copy). Until this lands, document the manual install path
   in `README.md`.
6. Resolve every `<...>` placeholder in the init flow at runtime
   (mcp-server path, plugin root, absolute project path).
7. Generate `worktree_scopes` and `project_id` in `.cloglog/config.yaml`.
8. Generate an `on-worktree-create.sh` that includes close-off-task
   registration (currently only this repo's hand-written copy does it).

Phase 3 — **multi-tenant GitHub App story**:

9. Document the "reuse the cloglog Apps" vs. "stand up your own" decision
   tree.
10. Move reviewer App constants out of `src/gateway/github_token.py` into a
    backend config table keyed by project. Add MCP tools or admin endpoints
    to register reviewer Apps per project.
11. Make the webhook tunnel + reviewer bot login per-project (already
    proposed in #3).

Phase 4 — **pin tests**:

12. Add the two pin tests catalogued in §8.
13. Wire fresh-repo init into CI as a smoke job (creates `tmp_path` repo,
    runs init, asserts placeholders are resolved).

**Smallest "first new project onboarded" milestone:** Phase 1 + steps 5/6/7
of Phase 2. That gets a self-contained plugin and an init that produces a
runnable `.cloglog/` for any project that already has the cloglog backend
+ MCP server reachable. Phase 3 (multi-tenant Apps) and Phase 4 (pin tests)
can land in parallel after the first project is onboarded and exposes the
real friction, rather than the friction we're guessing at.

**Parallelizable:** Phase 1 steps 1, 2, 3, 4 are independent of each other.
Phase 2 step 5 unblocks 6, 7, 8 but 6/7/8 are independent of each other once
5 lands. Phase 3 is independent of Phases 1–2. Phase 4 follows everything.

## Open questions

1. **Plugin install model.** Submodule, plugin marketplace, or copy-on-init?
   The current marketplace.json suggests the plugin is intended to be
   installed via a marketplace, but `/cloglog init` is written as if the
   plugin is already in `<project>/plugins/cloglog/`. Pick one model and
   make the init Step 0 reflect it.
2. **Backend topology — one shared or one per project?** Today there's one
   cloglog backend. If a second project uses the same backend, project_id
   discriminates rows — but `make prod`, the cloudflared tunnel, and the
   reviewer Apps are single-tenant. If projects each run their own backend,
   the operator needs to manage multiple backends, multiple tunnels, multiple
   credential files. Document the chosen topology, then make the rest follow.
3. **Credential location for non-cloglog projects.** The MCP server reads
   `~/.cloglog/credentials`. For a multi-project operator, do all projects
   share that file (one `CLOGLOG_API_KEY` per project, keyed by project name)?
   Today the file holds a single value. Either move to a per-project
   credentials file or change the format to a key-per-project map.
4. **Agent-vm sandbox assumption.** The `agent-vm` story (separate sandboxes
   per agent) is referenced in CLAUDE.md but not in plugin docs. Clarify:
   does `/cloglog init` need to set up agent-vm, or is that a separate
   operator concern handled before init runs?
5. **Reviewer-bot identity per project vs. shared.** Cloglog ships two
   reviewer Apps. Should every new project stand up its own reviewer Apps
   (App-create friction), or should the plugin support pointing at an
   already-installed reviewer App by login? Affects whether
   `reviewer_bot_logins` ends up a string list (shared) or a list of
   `{login, app_id, installation_id}` (per project).
6. **Should `mcp__cloglog__*` be renamed?** The MCP server name leaks the
   cloglog brand into every tool the agent sees. The cost of renaming is
   high (every skill greps `mcp__cloglog__`); the benefit is brand neutrality.
   Default recommendation: keep, treat "cloglog" as the system brand.

---

*Prepared for T-307 (F-52). Review the recommendations, decide on the
install/topology/credential model in §Open questions, and follow-up tasks
will be filed against the Phase 1–4 sequence.*
