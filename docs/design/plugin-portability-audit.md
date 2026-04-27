# Plugin Portability Audit (T-307)

**Status:** research / design — no implementation in this PR.
**Scope:** identify every place the cloglog plugin (`plugins/cloglog/`) and the
machinery it ships against (`mcp-server/`, `.cloglog/`, `scripts/`, root docs)
is implicitly bound to the cloglog repo itself, when the product premise is
that `/cloglog init` should onboard *any* project.

## User direction (2026-04-27)

After review, the user confirmed these design decisions, which override
several recommendations earlier in this audit:

- **Bots are shared across projects.** All projects use the same supervisor
  + reviewer Apps; the backend routes events to the correct project agent /
  worktree by project_id. Per-project bot setup is a *later* extension; for
  now we accept the shared-bot model.
- **Bot credentials live out-of-source in `~/.agent-vm/credentials/`** and
  are shared. Acceptable as-is.
- **Codex reviewer prompt should be project-agnostic** but each project's
  architecture is its own — leaving some review-prompt customisation to the
  user is correct.
- **Skills and the plugin must contain zero references to cloglog internals**
  — sources, paths, or architecture. Not every project is DDD. (This
  reaffirms §1's "skills cite cloglog source paths as authoritative"
  finding as a hard rule, not a nice-to-have.)
- **There is no agent-vm port allocation yet.** All references to agent-vm
  sandboxes / per-worktree port allocation in this audit are stale and
  should be ignored — that infrastructure does not exist.
- **Default `backend_url` should be `http://localhost:8001` (prod).** Port
  8000 is cloglog's own development server. Other projects always talk to
  the prod backend on 8001.
- **One MCP server, one backend.** The MCP server is found on first
  registration; no per-project MCP install/discovery is needed.
- **Plugin install is local-folder for now** (so changes are picked up
  without re-install). Marketplace publishing happens later when the
  plugin is ready.

The findings tables below are kept as the original evidence trail; the
**Recommended sequence** and **Open questions** sections have been pruned
to match these directions. Where a row's proposed fix conflicts with the
direction above, the direction above wins.

The product premise is that the **plugin** is the reusable surface and the
cloglog repo is just its first dogfood project. In practice we have built and
exercised the plugin only against this one repo; the audit below catalogues
every leak that surfaces the moment a second project tries to install it.

## Executive summary — top 6 friction points

Ranked by adoption blast radius. Each blocks `/cloglog init` from producing a
working multi-agent project on a fresh repo, end-to-end.

0. **Five plugin entry points parse `.cloglog/config.yaml` with `python3 -c 'import yaml'`** in violation of the project's own invariant at `docs/invariants.md:76`. On any host whose system Python lacks PyYAML — which is most of them — `plugins/cloglog/hooks/worktree-create.sh:35-41` exits before bootstrap (so `/cloglog launch` produces a worktree that never registers); `plugins/cloglog/hooks/quality-gate.sh:39-43` silently falls back to `make quality` even when the project configured `npm test`; `plugins/cloglog/hooks/protect-worktree-writes.sh:52-72` drops the scope guard entirely; `plugins/cloglog/hooks/enforce-task-transitions.sh:50-56` silently stops providing the client-side preflight (the backend already blocks agent → `done` transitions at `src/agent/services.py:417` and `:501`, so this is a UX/portability degradation, not a safety bypass); and `plugins/cloglog/skills/launch/SKILL.md:223-229` (whose template materialises `.cloglog/launch.sh`) resolves `backend_url` to `http://localhost:8000` on the shutdown path so `unregister-by-path` posts to the wrong backend, leaving the worktree stuck online. The fix is mechanical for the four scalar-key parsers (replace each with the grep+sed pattern from `.cloglog/on-worktree-create.sh:88-105`, hoisted into a shared helper); `protect-worktree-writes.sh` reads the **nested `worktree_scopes` mapping** that grep+sed cannot represent, so it needs either a plugin-shipped Python parser (e.g. `tomllib`-style stdlib-only YAML, or a vendored mini-parser) or a flatter config format. Until both fixes land no other portability work matters — agents on a fresh host can't even register or unregister cleanly.
1. **`/cloglog init` emits unresolved placeholders.** The plugin is
   designed to be installed via `claude plugins install` per
   `docs/superpowers/specs/2026-04-12-cloglog-plugin-extraction-design.md:10-29`
   (one shared backend, plugin discovered through `${CLAUDE_PLUGIN_ROOT}` —
   not vendored into each consumer repo). The portability blocker is that
   the init skill emits literal `<absolute-path-to-project>`,
   `/path/to/mcp-server/dist/index.js`, and `<path to plugins/cloglog>`
   placeholders into `.claude/settings.json` and the prompt instructions
   (`plugins/cloglog/skills/init/SKILL.md:62,77,280`) that are never
   resolved at runtime. A fresh repo following the documented flow lands a
   broken `.claude/settings.json`. Tangentially: `scripts/gh-app-token.py`,
   `scripts/wait_for_agent_unregistered.py`, and `scripts/install-dev-hooks.sh`
   are referenced from skills via project-relative paths — those need to
   move into `${CLAUDE_PLUGIN_ROOT}/scripts/` so an installed plugin can
   reference them without a per-repo copy.
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
   regenerated per-worktree by the launch skill (already gitignored at
   `.gitignore:17`), but its runtime contents embed operator-host absolute
   paths (`launch.sh:3-4` on this worktree) — host-specific runtime state
   that must not be copied between operators. `.cloglog/on-worktree-create.sh` calls
   `${REPO_ROOT}/scripts/worktree-infra.sh` (a cloglog-only file) and
   `curl /api/v1/agents/close-off-task` against a backend that may not be
   running. The init skill emits scaffolding for `on-worktree-create.sh`
   based on `pyproject.toml`/`package.json`/`Cargo.toml`, and the result is
   `uv sync` / `npm install` only — which is correct per the design
   contract. Cloglog's own per-worktree Postgres and close-off-task
   plumbing are project-specific extensions a downstream project opts into.
5. ~~**GitHub App identity is single-tenant by design.**~~ **Resolved per
   user direction (2026-04-27):** all projects share the same bots; the
   backend routes events to the correct agent/worktree by project_id. Bot
   credentials live in `~/.agent-vm/credentials/` out-of-source and are
   shared across projects. The cross-org Repository-access flow (cloglog
   org admin invites the App into the consumer repo) covers a non-cloglog
   project's repository. No per-project App story needs to land for the
   first new project onboarding. The original finding is preserved in the
   §9 evidence trail; do not action it. *(Per-project bot identities is a
   later extension once cloglog has multiple production tenants.)*

## Findings by category

Citations are `file:line` against this worktree (HEAD of
`wt-t307-plugin-portability-audit`).

### 1. Plugin code (`plugins/cloglog/`)

| File:line | What's hardcoded | Impact on new project | Proposed fix |
|---|---|---|---|
| `plugins/cloglog/.claude-plugin/plugin.json:2-3` | name `cloglog`, description `cloglog-managed projects` | Cosmetic; reads as a cloglog-specific tool | Reframe description as project-agnostic ("multi-agent kanban workflow") |
| `plugins/cloglog/.claude-plugin/marketplace.json:2,8-9` | Marketplace name `cloglog-dev` | Reads as one-org marketplace | OK if intent is single-source; otherwise rename `cloglog-marketplace` |
| `plugins/cloglog/skills/init/SKILL.md:43,387` | Default `backend_url: http://localhost:8000` | Wrong default for non-cloglog consumers. Per user direction (2026-04-27) the prod backend lives on `http://localhost:8001`; port 8000 is reserved for cloglog's own dev server. A new project initialised today against :8000 will silently miss the prod backend | Change init's default to `http://localhost:8001`. Document that :8000 is cloglog-internal dev only |
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
| `plugins/cloglog/skills/demo/SKILL.md:40` + `scripts/check-demo.sh:31` | Allowlist regex is a **negative** exclusion list (`grep -vE '^docs/\|…\|^plugins/[^/]+/(hooks\|skills\|agents\|templates)/\|…'`) — `src/`, `frontend/src/`, `mcp-server/src/` are *not* in the regex and a second repo's source paths fall through to the classifier as expected. The genuinely cloglog-coupled entry is `^plugins/[^/]+/(hooks\|skills\|agents\|templates)/`, which assumes any plugin-shaped repo follows that subdir convention | Cosmetic for non-plugin projects; relevant for a project that ships its *own* plugin alongside a different layout | Make the plugin-path entry configurable via `.cloglog/config.yaml` (`demo_allowlist_paths: [...]`) — leave the rest as-is. Pinned by `tests/test_check_demo_allowlist.py`; update both regex sites in lockstep |
| `plugins/cloglog/skills/demo/SKILL.md:242,248,255,264` | `X-Dashboard-Key: cloglog-dashboard-dev` curl examples | Two-fold leak: (a) cloglog-specific dashboard key; (b) implies every project shares the same auth header | Replace with a placeholder/`${DASHBOARD_KEY}` env var; document where the key comes from |
| `plugins/cloglog/skills/demo/SKILL.md:279` | "`tests/conftest.py` has a session-autouse fixture that opens a PostgreSQL connection" | cloglog's conftest behavior elevated to general advice | Move to a "cloglog-specific notes" footnote |
| `plugins/cloglog/skills/demo/SKILL.md:422` | `grep -c "\-\-dangerously-bypass" src/gateway/review_engine.py` example | cloglog-source example | Replace example with a generic one |
| `plugins/cloglog/agents/worktree-agent.md:29,55` | "run whatever the project's CLAUDE.md defines (e.g., `make quality`)" + the T-NEW-b workaround block citing `src/agent/services.py:237` | First case is fine (acknowledges variation); second case is repo-specific | Delete T-NEW-b once landed; otherwise move workaround to a single shared skill section |
| `plugins/cloglog/templates/claude-md-fragment.md:14` | "matches what `plugins/cloglog/skills/github-bot` and `plugins/cloglog/agents/worktree-agent.md` require" | Internal cross-references inside the injected fragment leak the plugin's own filesystem layout into the project's CLAUDE.md | Drop the file references; document the contract directly |
| `plugins/cloglog/templates/claude-md-fragment.md:32` | Same T-NEW-b citation | Same |
| `plugins/cloglog/templates/codex-review-prompt.md:61-63` | Route decorator regex assumes routers in `src/**`; component regex assumes `frontend/src/**` | Codex review prompt won't trigger on projects with different layouts | Make the regex paths configurable, or generate the prompt per-project (init Step 7 already partly does this) |
| `plugins/cloglog/templates/codex-review-prompt.md:61` (cont.) | Enumerates `src/board/routes.py`, `src/agent/routes.py`, `src/document/routes.py`, `src/gateway/routes.py`, `src/gateway/sse.py`, `src/gateway/webhook.py` by name | Cloglog DDD layout enumerated literally | Replace with route-decorator regex only; drop the enumeration |
| `plugins/cloglog/scripts/auto_merge_gate.py:11,14,107` | Cites `src/gateway/review_engine.py` and `src/**`/`frontend/src/**`/`mcp-server/src/**`/`tests/**` allowlist | Hardcoded source-tree assumptions inside the gate script | Read allowlist from config; use the same `demo_allowlist_paths` proposal as above |
| `plugins/cloglog/hooks/worktree-create.sh:35-41` + `plugins/cloglog/hooks/quality-gate.sh:39-43` + `plugins/cloglog/hooks/protect-worktree-writes.sh:52-72` + `plugins/cloglog/hooks/enforce-task-transitions.sh:50-56` + `plugins/cloglog/skills/launch/SKILL.md:223-229` (template that generates `.cloglog/launch.sh`) | Five plugin entry points parse `.cloglog/config.yaml` with `python3 -c 'import yaml'` | **Violates the project's own invariant** at `docs/invariants.md:76` — system Python on most hosts has no PyYAML, the import fails silently, and: (a) `worktree-create.sh` exits before running `.cloglog/on-worktree-create.sh`, so `/cloglog launch` creates a worktree that never registers and never bootstraps; (b) `quality-gate.sh` falls through to `make quality` even when the project configured `npm test`; (c) `protect-worktree-writes.sh` exits 0 with no scope guard, removing the safety net the rule was written to provide; (d) `enforce-task-transitions.sh` is wired into `mcp__cloglog__update_task_status\|mcp__cloglog__complete_task` (`plugins/cloglog/settings.json:86-91`); the backend already rejects agent-driven `done` transitions at `src/agent/services.py:417,501`, so the bypass is **not** a safety boundary — but the silent skip removes the client-side preflight that catches violations before they hit the API, degrading the agent UX and the portability story; (e) the generated `.cloglog/launch.sh` resolves `backend_url` to `http://localhost:8000` on the shutdown path, so `unregister-by-path` posts to the wrong backend and the worktree stays stuck online until timeout. **This is a more immediate portability blocker than the prose issues below.** The already-fixed sibling hook `.cloglog/on-worktree-create.sh:88-105` documents the failure mode and the grep+sed pattern that replaces it | Two-track fix: (1) **Scalar-key parsers** (`backend_url`, `quality_command`, `project_id`, `project`) — replace `import yaml` in `worktree-create.sh`, `quality-gate.sh`, `enforce-task-transitions.sh`, and the `launch` skill template with a shared grep+sed helper modeled on `.cloglog/on-worktree-create.sh:88-105` + `plugins/cloglog/hooks/agent-shutdown.sh:62-74`. (2) **Nested-mapping parser** (`worktree_scopes`) — `protect-worktree-writes.sh` cannot use grep+sed; it needs a plugin-shipped Python parser (a vendored mini-YAML reader, or migrate `worktree_scopes` to a flat shape representable as `key=path1,path2`). Pin tests cover (i) zero `import yaml` in scalar-key sites under `plugins/cloglog/hooks/`, (ii) `protect-worktree-writes.sh` parses correctly without global PyYAML, (iii) the launch template's emitted launcher (extend `tests/plugins/test_launch_skill_uses_abs_paths.py:35-103`) |
| `plugins/cloglog/hooks/protect-worktree-writes.sh:3,32-42` | Hook reads `worktree_scopes` from `.cloglog/config.yaml` (good) — but **cloglog's** config.yaml ships scopes keyed to `src/board/`, `src/agent/`, `src/document/`, `src/gateway/`, `frontend/`, `mcp-server/`, `assign`, `e2e` (`.cloglog/config.yaml:7-15`) | A new project must hand-author scopes for its own layout. `/cloglog init` does *not* generate this section, so a fresh project starts with no scope guard at all (compounded by the `import yaml` row above — even a project that *does* author scopes loses enforcement on hosts without PyYAML) | Either (a) generate a permissive default scope from the tech stack, or (b) make the hook a no-op when no `worktree_scopes` key is present and document that explicitly. Land the YAML parser fix above in the same change |
| `plugins/cloglog/hooks/quality-gate.sh:42-43` | Falls back to `make quality` if config is missing | Reasonable default in principle, but combined with the `import yaml` row above it means **even a project that correctly sets `quality_command: npm test` runs `make quality` instead** on any host without global PyYAML — silent and the wrong way around (a `make quality` on a node project usually fails fast, but on a project that has *no* Makefile target named `quality` the hook prints "make: *** No rule…" once and the operator has no idea why the lint command they configured was ignored) | Land the YAML parser fix above; then make the missing-config branch error out with "no quality_command in .cloglog/config.yaml" rather than silently running a make target |
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
| `on-worktree-create.sh` | 145 lines: shutdown-artifacts reset, `worktree-infra.sh up`, `uv sync --extra dev`, frontend install conditional on `wt-frontend*`, `mcp-server` install conditional on `mcp-server/package.json`, close-off-task POST to backend with project API key, env-driven `_resolve_backend_url`/`_resolve_api_key` helpers | Init produces ~5 lines: `cd $WORKTREE_PATH; uv sync` (or `npm install`, etc.) | Init's minimal output matches the design contract — the heavyweight content here is cloglog-specific. Close-off-task POST and per-worktree Postgres are project-specific opt-ins; the agent-vm port allocation referenced in earlier drafts of this row does **not exist yet** (per user direction 2026-04-27) — disregard those references |
| `on-worktree-destroy.sh` | Calls `worktree-infra.sh down` | Init produces an empty stub | Same gap |
| `launch.sh` | Auto-generated by the launch skill per worktree; on this worktree the file embeds absolute `/home/sachin/code/cloglog/...` paths in `WORKTREE_PATH` and `PROJECT_ROOT` (lines 3-4) | Skill generates per-worktree at launch time | Already gitignored at `.gitignore:17`, so it's not a *tracked* leak — but the **runtime contents are still operator-host-specific** and any tooling that reads it from a different host won't find the right paths. Document that `launch.sh` is regenerated per-host and must not be copied between operators. |
| `inbox` | Runtime state, gitignored (`init` Step 8 adds it) | Same | OK |

### 5. Skills — additional cross-cutting issues

Beyond the per-skill citations in §1, two systemic patterns:

- **Skills assume `pwd` is the project root.** `plugins/cloglog/hooks/session-bootstrap.sh:11` uses `PROJECT_DIR=$(pwd)`. The setup skill repeatedly says `<current working directory>` in place of `$PROJECT_ROOT`. This works for the common case (operator launches Claude from the project root) but breaks on cd-into-subdir starts, including the Bash-tool's persistent CWD model. Consider deriving project root from `git rev-parse --show-toplevel` consistently. (`plugins/cloglog/skills/close-wave/SKILL.md:144` and `plugins/cloglog/skills/reconcile/SKILL.md:32` already do this — make it the universal pattern.)
- **Skills cite `<project_root>/.cloglog/inbox` versus `<worktree_path>/.cloglog/inbox` inconsistently in prose.** The contract is correct (main inbox lives at project root; per-worktree inbox lives in the worktree) but readers confuse the two on first read. Add a single "Inbox locations" sub-section in `claude-md-fragment.md` or a top-level skills/README that the others link to.

### 6. `/cloglog init` walkthrough on a fresh repo

I created `/tmp/audit-fresh-repo` (`git init` + a one-line README) and walked
through the steps that `plugins/cloglog/skills/init/SKILL.md` would execute,
*without running them*. Per the design spec
(`docs/superpowers/specs/2026-04-12-cloglog-plugin-extraction-design.md:10-29,
301-315`) the plugin is installed via `claude plugins install`, the backend
is one shared service across projects, and the `.cloglog/on-worktree-create.sh`
hook is **optional** project-specific bootstrap — a project with zero custom
setup still gets the full workflow. The audit walks the gaps that prevent the
init flow from producing a working repo against that contract; it does **not**
recommend vendoring the plugin or universalising cloglog's worktree-infra.

| Step | What init does | What happens on fresh repo |
|---|---|---|
| (prereq) | Plugin installed via `claude plugins install` | The skill assumes the plugin is reachable through `${CLAUDE_PLUGIN_ROOT}` (`plugins/cloglog/settings.json:9-20,42-43,69-70,89-90`). Confirmed working architecture; gap below is in what the init skill emits, not in the install model |
| 1a | Detect project name from `basename $(pwd)` | Works |
| 1b | Detect quality command (Makefile/package.json/Cargo/pyproject) | Works for the four detected stacks; fails closed for anything else (asks user) |
| 1c | Default backend_url `http://localhost:8000` | **Wrong default** — per user direction (2026-04-27) prod is :8001 and :8000 is reserved for cloglog's own dev server. Init should default to `http://localhost:8001` |
| 2 | Call `mcp__cloglog__get_board` to check project exists | **Cannot run before MCP is configured (Step 3).** Step 2 is out of order — at step 2 the MCP server has not been configured for this project, and the project API key is not yet in `~/.cloglog/credentials`. The MCP tool will not be loaded. The skill papers over this with "the user will need to register it through the backend API or MCP tools" — i.e., manual |
| 3 | Inject `cloglog` MCP server into `.claude/settings.json` with placeholder `"args": ["/path/to/mcp-server/dist/index.js"]` | The placeholder is **literal**. The skill never asks the operator where their MCP server build lives. On first session restart the MCP server fails to start, the agent has no `mcp__cloglog__*` tools, and the SessionStart hook prints "Run /cloglog setup" — which then fails the same way |
| 4a | Write `.cloglog/config.yaml` with project_name/backend_url/quality_command | Misses `project_id`, `worktree_scopes`, `prod_worktree_path`. See gap in §4 |
| 4b | Write `on-worktree-create.sh` for detected stack | Generates `uv sync` / `npm install` per the design contract — this is correct; the spec (`docs/superpowers/specs/2026-04-12-cloglog-plugin-extraction-design.md:41-47,301-315`) explicitly says infrastructure setup (ports, DBs, deps) is project-provided and *optional*. **Cloglog's** hand-written `.cloglog/on-worktree-create.sh` adds close-off-task POST and `worktree-infra.sh` (port allocation, per-worktree Postgres) — those are cloglog-specific extensions, not init responsibilities, and downstream projects opt in by editing their own script. The actual gap here is that init's tech-stack detection is limited (Python/uv, Node, Rust); a project on a stack outside those four gets an empty stub |
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

**Net assessment:** Per the design spec the plugin is operator-installed via
`claude plugins install`, so vendoring is *not* a portability blocker. The
minimum changes to make `/cloglog init` produce a working repo are:
(a) resolve the literal `<absolute-path-to-project>`,
`/path/to/mcp-server/dist/index.js`, and `<path to plugins/cloglog>`
placeholders to concrete values at runtime;
(b) replace Step 2's `mcp__cloglog__get_board` call with a non-MCP admin/backend bootstrap (the MCP server can't load before credentials + restart on a fresh repo — see Phase 2 step 7 for the concrete two-phase flow);
(c) generate `worktree_scopes` and `project_id` in `.cloglog/config.yaml`;
(d) move project-relative script references (`scripts/gh-app-token.py`,
`wait_for_agent_unregistered.py`, `install-dev-hooks.sh`) into
`${CLAUDE_PLUGIN_ROOT}/scripts/` so the installed plugin can resolve them;
(e) document a bot-setup story that doesn't depend on the operator having a
sibling cloglog clone in `~/code/`.

Cloglog's own close-off-task POST and `worktree-infra.sh` setup are
cloglog-specific extensions to its `.cloglog/on-worktree-create.sh` and stay
out of the generic init contract — projects that need similar machinery edit
their own optional bootstrap script.

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

There is no dedicated fresh-repo `/cloglog init` portability smoke test. Some
plugin-adjacent tests do exist — e.g.
`tests/test_install_dev_hooks_guard.py` exercises a fresh repo for the
pre-commit hook, `tests/test_on_worktree_create_mcp_install.py` covers the
hook's MCP-install branch — but none asserts that init produces a working
project from a clean slate, and none pins the absence of cloglog-specific
literals from generated artifacts.

| Gap | Proposed fix |
|---|---|
| No fresh-repo `/cloglog init` smoke test | Add `tests/plugin/test_init_on_fresh_repo.py` that creates a `tmp_path` repo, runs the init steps non-interactively, and asserts: (a) **no unresolved placeholders** like `<absolute-path-to-project>`, `<path to plugins/cloglog>`, `/path/to/mcp-server/dist/index.js`; (b) **no repo-specific literals** like `../cloglog-prod`, `cloglog.voxdez.com`, hardcoded reviewer-bot logins, `/home/sachin/...`. Two carve-outs: (i) the **brand surface** (`cloglog`, `mcp__cloglog__*`, the MCP server name `cloglog-mcp`, the `~/.cloglog/credentials` path) is intentionally retained — `plugins/cloglog/skills/init/SKILL.md:69-77,155-165` writes those literals on purpose; (ii) `.cloglog/launch.sh` is **exempt** from the host-specific-literals assertion — `plugins/cloglog/skills/launch/SKILL.md:206-221` and `tests/plugins/test_launch_skill_uses_abs_paths.py:35-103` pin that the launcher must contain absolute `WORKTREE_PATH`/`PROJECT_ROOT` to prevent the T-284 cwd-drift regression. For the launcher, write the inverse assertion: placeholders must be resolved AND absolute paths must be present |
| No portability assertion that skills don't grow new cloglog citations | Add a pin test that greps `plugins/cloglog/` for the **specific** strings catalogued above (repo-specific paths, `cloglog-prod`, reviewer-bot logins, dashboard keys, `cloglog.voxdez.com`, source-tree line citations) and fails on regressions. Echo the existing pattern from `tests/test_mcp_json_no_secret.py`. Do NOT pin against the brand-surface literals — see above |

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

Phase 0 — **unblock fresh-host execution** (must land first; split into two tracks):

0a. **Scalar-key parsers** (mechanical, single shared helper). Replace `python3 -c 'import yaml'` blocks at:
   - `plugins/cloglog/hooks/worktree-create.sh:35-41` (reads `backend_url`)
   - `plugins/cloglog/hooks/quality-gate.sh:39-43` (reads `quality_command`)
   - `plugins/cloglog/hooks/enforce-task-transitions.sh:50-56` (reads `project_id`/`project`)
   - `plugins/cloglog/skills/launch/SKILL.md:223-229` template (reads `backend_url`; regenerate `.cloglog/launch.sh` after)
   …with the grep+sed pattern from `.cloglog/on-worktree-create.sh:88-105` + `plugins/cloglog/hooks/agent-shutdown.sh:62-74`, hoisted into one shared helper sourced by all four sites.

0b. **Nested-mapping parser** (`plugins/cloglog/hooks/protect-worktree-writes.sh:52-72` reads the `worktree_scopes` mapping). Grep+sed cannot represent the nested shape. Two options: (i) ship a plugin-vendored stdlib-only parser (small, hand-rolled — only the YAML subset cloglog uses); (ii) flatten `worktree_scopes` in `.cloglog/config.yaml` to `worktree_scope_<name>: path1,path2` so it falls into the scalar-helper case. Decide and land alongside 0a.

Pin tests: (i) zero `import yaml` substrings at the four scalar sites; (ii) `protect-worktree-writes.sh` parses correctly with `python3 -c 'import yaml; raise ImportError()'` simulated; (iii) extend `tests/plugins/test_launch_skill_uses_abs_paths.py:35-103` to assert the template's `_backend_url` block uses the shared helper.

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
4. Document that `.cloglog/launch.sh` is host-specific runtime state
   (already gitignored at `.gitignore:17`); add the warning to the launch
   skill so a future operator never copies it across hosts.

Phase 2 — **make `/cloglog init` actually work on a fresh repo**:

5. Document the operator install flow (`claude plugins install <marketplace>`)
   in `README.md` and the init skill's prerequisites. The plugin is reached
   through `${CLAUDE_PLUGIN_ROOT}` once installed — no vendoring.
6. Resolve every `<...>` placeholder in the init flow at runtime
   (mcp-server path → resolve from `${CLAUDE_PLUGIN_ROOT}/../mcp-server`
   when bundled, or prompt the operator; plugin root → `${CLAUDE_PLUGIN_ROOT}`;
   absolute project path → `git rev-parse --show-toplevel`).
7. **Replace** init Step 2 with a non-MCP project bootstrap path.
   Reordering alone is insufficient: `mcp-server/src/index.ts:16` exits
   without `CLOGLOG_API_KEY`, `mcp-server/src/server.ts:51,435` requires
   `currentProjectId` (set only by `register_agent`), and
   `register_agent` itself needs a valid project API key
   (`src/agent/routes.py:56`). On a fresh repo none of those preconditions
   hold yet. Concrete shape: (a) Step 2 becomes a dedicated
   admin/backend HTTP call (e.g. `POST /api/v1/admin/projects` with the
   operator's admin token) that creates-or-looks-up the project and returns
   the project API key; (b) the skill writes the key to
   `~/.cloglog/credentials` and `project_id` to `.cloglog/config.yaml`;
   (c) the operator restarts Claude Code so the MCP server picks up the
   new credentials; (d) only after restart does the skill use MCP tools.
   Document the two-phase flow in the init skill.
8. Generate `worktree_scopes` and `project_id` in `.cloglog/config.yaml`.
   `worktree_scopes` should be a permissive default keyed off the detected
   stack, with the existing cloglog scope set staying as-is in this repo.
9. Keep `.cloglog/on-worktree-create.sh` generation focused on the
   tech-stack bootstrap the spec mandates (`uv sync` / `npm install` /
   etc.). Cloglog's close-off-task POST and `worktree-infra.sh` plumbing
   are project-specific extensions and stay in cloglog's hand-written
   copy; downstream projects opt in by editing their own script.

~~Phase 3 — multi-tenant GitHub App story~~ — **Dropped per user direction
(2026-04-27).** All projects share the cloglog supervisor + reviewer Apps;
the backend already routes by `project_id`, and bot credentials live
out-of-source in `~/.agent-vm/credentials/` shared across projects. The
cross-org Repository-access flow covers consumer repos. Per-project bot
identities are a *later* extension once cloglog has multiple production
tenants — file then, not now.

Phase 3 — **pin tests** (was Phase 4):

10. Add the two pin tests catalogued in §8 (fresh-repo `/cloglog init`
    smoke + `plugins/cloglog/` regression grep). Excluded from both:
    brand-surface literals (intentional) and `.cloglog/launch.sh`
    (intentional absolute paths).
11. Wire fresh-repo init into CI as a smoke job (creates `tmp_path` repo,
    runs init non-interactively, asserts placeholders are resolved and
    no host-specific literals leak).

**Smallest "first new project onboarded" milestone:** Phase 1 + steps 5/6/7
of Phase 2. That gets a self-contained plugin and an init that produces a
runnable `.cloglog/` for any project that talks to the prod backend on
:8001 with a project API key. Phase 3 (pin tests) follows.

**Parallelizable:** Phase 1 steps 1, 2, 3, 4 are independent of each other.
Phase 2 step 5 unblocks 6, 7, 8, 9 but those four are independent of each
other once 5 lands. Phase 3 follows everything.

## Open questions

Most original questions resolved by user direction (2026-04-27); see the
preamble. Remaining:

1. **Marketplace publishing timeline.** Install is local-folder for now so
   plugin edits are picked up live. Open: when does cloglog publish to a
   marketplace, what marketplace, and does the install command in init
   docs change at that point? Defer until after the first new project
   onboards.
2. **Codex review-prompt customisation surface.** User direction is that
   the reviewer prompt should be project-agnostic *but* each project has
   its own architecture, so some customisation must be left to the user.
   Open: what's the minimum-viable customisation API — a single
   `.github/codex/prompts/review.md` the project hand-writes (today's
   model), or a config-driven set of stack-specific fragments the plugin
   composes? Defer until at least one non-cloglog project has run codex
   review.
3. **Credential format for multi-project operator.** Today
   `~/.cloglog/credentials` holds a single `CLOGLOG_API_KEY`. If one
   operator runs two projects against the shared backend, they need two
   keys. Open: per-project credentials file (`~/.cloglog/credentials.<project>`),
   or single-file map (`CLOGLOG_API_KEY_<project>=...`)? Lean towards
   per-project files for permission isolation.
4. **Should `mcp__cloglog__*` be renamed?** The MCP server name leaks the
   cloglog brand into every tool the agent sees. The cost of renaming is
   high (every skill greps `mcp__cloglog__`); the benefit is brand
   neutrality. Default recommendation: **keep**, treat "cloglog" as the
   system brand. (User direction confirms this — brand surface like
   `mcp__cloglog__*` is intentionally retained.)

Resolved per 2026-04-27 user direction (recorded for posterity, not
re-debated):
- ~~Plugin install model~~ → local-folder install for now; marketplace later.
- ~~Backend topology~~ → one shared backend, project_id-scoped.
- ~~Agent-vm assumption~~ → no agent-vm yet; references in this audit are stale.
- ~~Reviewer-bot identity per project~~ → all projects share the same bots.

---

*Prepared for T-307 (F-52). Follow-up tasks file against Phase 0 → 3.*
