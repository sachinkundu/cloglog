# Silent-Failure Invariants

Rules whose breakage does not fail a test, lint, or build on its own — they
ship broken, and production catches them. Each entry names the invariant and
the pin test that guards it. Adding a new entry requires a pin test.

Run the full set with `make invariants`.

## Gateway / auth

### `/api/v1/agents/*` permissive bucket

The gateway middleware (`src/gateway/app.py`) lets any `Authorization` header
through for `/api/v1/agents/*` and defers the real check to each route's
`Depends(...)`. A new agent route added without an explicit auth dep
(`SupervisorAuth`, `CurrentProject`, `CurrentAgent`, or `McpOrProject`) is
**silently open** — a bogus bearer returns 200.

**Pin:** `tests/agent/test_integration.py::TestForceUnregisterAPI::test_force_unregister_rejects_agent_token`

### Non-agent routes accepting MCP credentials

`ApiAccessControlMiddleware` only presence-checks credential headers on
non-agent routes; it does not validate the bearer value. A new route added
without `CurrentMcpService` / `CurrentMcpOrDashboard` Depends is silently
open to any bearer under `X-MCP-Request: true`.

**Pin:** `tests/e2e/test_access_control.py::test_worktrees_with_invalid_mcp_bearer_is_rejected`

### Destructive endpoints that must reject self-initiation need `McpOrProject`, not `SupervisorAuth`

`SupervisorAuth` (`src/gateway/auth.py::get_supervisor_auth`) accepts three
credential paths: (1) MCP service key, (2) project API key, and (3) **the
target agent's own token when it matches the URL's `worktree_id`**. Path 3
is deliberate for routes like `request_shutdown` — an agent may gracefully
end itself. Path 3 is **not** acceptable for a nuclear path like
`force_unregister`: a wedged or malicious agent must not be able to
force-unregister itself. For that class of route, use `McpOrProject` (which
has no agent-token path) and ship a regression named
`test_*_rejects_agent_token`. Reviewing only for "does this route use
`CurrentAgent`" misses the hole; review for "can the agent's own token
pass this Depends."

**Pin:** `tests/agent/test_integration.py::TestForceUnregisterAPI::test_force_unregister_rejects_agent_token`

## Review engine

### `resolve_pr_review_root` — four strategies + SHA drift + repo-aware refusal

Per-PR review root resolver has four strategies in order: `find_by_pr_url`
(PR → task → worktree, covers main-agent close-out PRs), `find_by_branch`
(agent worktree PRs), per-repo registry (`REVIEW_REPO_ROOTS` mapping
`owner/repo → filesystem path`, T-350), then legacy host-level fallback
(`REVIEW_SOURCE_ROOT` / `Path.cwd()`). After any strategy hits, a SHA
mismatch against `event.head_sha` materialises a disposable checkout
under `<main>/.cloglog/review-checkouts/<sha8>-<pr>`. Return type is
`PrReviewRoot(path, is_temp, main_clone) | None` — callers must inspect
`is_temp` for cleanup AND handle the `None` refusal case. The resolver
returns `None` when `REVIEW_REPO_ROOTS` is non-empty AND the event's
`repo_full_name` is absent AND no worktree on the host owns the branch;
the engine surfaces this as a one-shot `unconfigured_repo` skip comment
instead of routing the review to the wrong repo's source (the antisocial
PR #2 incident shape). When `REVIEW_REPO_ROOTS` is empty (single-repo
hosts), the legacy fallback applies and the resolver never returns
`None` — preserving pre-T-350 behaviour. External-fork PRs in
single-repo mode fall through to a `review_source_drift` warning by
design (see `docs/design/two-stage-pr-review.md` §9.6).

**Pin:** `tests/gateway/test_review_engine.py::TestResolvePrReviewRoot` +
`tests/gateway/test_review_engine.py::TestResolvePrReviewRootRepoRouting`

### Review body `_SEVERE_SEVERITIES` writer/reader parity

`ReviewLoop._reached_consensus` refuses to short-circuit an `approve`
verdict that carries a `critical`/`high` finding. `_format_review_body`
must key on the same predicate so the body's icon prefix matches the
consensus state. The shared severity set is `review_loop._SEVERE_SEVERITIES`;
`review_engine._SEVERE_SEVERITIES` mirrors it. When a new reader of any
structured output another module writes is added, lift the shared
predicate — don't re-derive it.

**Pin:** `tests/gateway/test_review_engine.py::TestLatestCodexReviewIsApproval`

## Hooks / infra

### Hook scripts parse `.cloglog/config.yaml` without `import yaml`

Hook scripts run under the system `python3`, which has no PyYAML. A
`python3 -c 'import yaml'` snippet silently swallows `ImportError` and
returns the default `http://localhost:8000`, sending POSTs to the wrong
port with every caller appearing to succeed. Two parsers ship with the
plugin, picked by the shape of the value being read:

- **Top-level scalar keys** (`backend_url`, `quality_command`, `project`,
  `project_id`) — use `plugins/cloglog/hooks/lib/parse-yaml-scalar.sh` or
  the inline `grep '^key:'` + `sed` shape it canonicalises (precedent:
  `plugins/cloglog/hooks/agent-shutdown.sh:64-68`).
- **Nested `worktree_scopes:` mapping** — use
  `plugins/cloglog/hooks/lib/parse-worktree-scopes.py` (stdlib-only). The
  nested shape can't be represented by `grep+sed`; the dedicated parser
  exists precisely so `protect-worktree-writes.sh` doesn't fall back to
  `import yaml`.

**Pins:**
- `tests/test_on_worktree_create_backend_url.py::test_hook_does_not_invoke_python_yaml`
- `tests/plugins/test_no_python_yaml_in_scalar_hooks.py`
- `tests/plugins/test_parse_worktree_scopes.py`

### `CLOGLOG_API_KEY` never in `.mcp.json`

Project API keys live in `~/.cloglog/credentials` (0600). The MCP server
resolves them from env first, then the credentials file; missing →
`process.exit(78)`. `.mcp.json` is checked into git and must not carry
a secret.

**Pin:** `tests/test_mcp_json_no_secret.py`

## Persistence

### `DATABASE_URL` is required, no silent shared-DB fallback

`Settings.database_url` (`src/shared/config.py`) has **no default**.
`alembic.ini` carries no `sqlalchemy.url` default. `src/alembic/env.py`
sources its URL from `Settings`, which loads `.env` and raises
`ValidationError` when `DATABASE_URL` is unset. A backend or alembic
invocation without an explicit `DATABASE_URL` aborts at startup instead of
silently connecting to the shared `cloglog` DB. Each environment supplies
its own `DATABASE_URL` via `.env`: prod (`cloglog`), dev (`cloglog_dev` —
created by `make dev-env`), each worktree (`cloglog_wt_<name>` — created
by `scripts/worktree-infra.sh`). Silent-failure shape this guards: a
worktree backend started without sourcing its `.env` used to migrate the
prod `cloglog` DB; a `make dev` run without a dev `.env` did the same.
Now both fail with a clear ValidationError naming `database_url`.

**Pin:** `tests/test_database_url_required.py`

### Upsert preserves existing columns on empty input

When an upsert accepts partial data (e.g., `upsert_worktree(branch_name=...)`),
empty-string / null from the caller means "preserve existing," not
"overwrite with empty." A transient probe failure or reconnect must not
clobber a populated column.

**Pin:** `tests/agent/test_unit.py::TestAgentService::test_register_reconnect_preserves_branch_when_caller_sends_empty`

### Migrations do not mark live data offline or soft-delete

Alembic migrations in `src/alembic/versions/` must be additive against
live state. Destructive cleanup (marking agents offline, soft-deleting
rows based on transient probes, rewriting status columns) belongs in
`/cloglog reconcile`, not in migrations that run on every deploy.
Backfilling a newly-added column is the one allowed data write.

**Pin:** `tests/test_no_destructive_migrations.py::test_no_destructive_migrations`
(plus `::test_destructive_patterns_reference_real_tables`, a self-check
that cross-references every table named in the destructive regexes
against `Base.metadata` so a table rename can't quietly make a pattern
dead — caught on PR #206 round 2 when `agent_sessions` was flagged in
place of the real `sessions` table).

## Production runtime

### `make prod` / `make prod-bg` invoke gunicorn with `--capture-output`

Without `--capture-output`, gunicorn worker stdout/stderr (FastAPI
tracebacks, codex CLI invocation errors, review_engine exceptions) goes to
the controlling terminal, not `--error-logfile`. In `--daemon` mode there
is no controlling terminal, so the output is dropped. PR #260 (T-231)
caught this: the review_engine swallowed an exception on a synchronize
webhook and left no log to diagnose from. A future Makefile edit that
drops the flag from either invocation would silently regress the same
class of failure — production keeps booting, gunicorn's own boot/shutdown
lines still show up in the log, and only an unrelated incident makes the
gap visible.

**Pin:** `tests/test_makefile_gunicorn_invocation.py`

## Demo gate

### `scripts/check-demo.sh` auto-exempts only fully-allowlisted diffs

The gate's "docs-only" short-circuit (the `grep -vE` regex at line 31)
must exempt a branch if, and only if, every changed file matches the
allowlist: `docs/`, `CLAUDE.md`, `.claude/`, `.cloglog/`, `scripts/`,
`.github/`, `tests/`, `Makefile`, `plugins/*/{hooks,skills,agents,templates}/`,
`pyproject.toml`, `ruff.toml`, `package-lock.json` (nested or root),
`*.lock`. A single file outside that set forces the demo gate. The failure mode the pin guards is a silent regression: an edit
that drops a listed path (reintroducing false positives for agents who
touch `Makefile` or `tests/`) OR that widens the allowlist to match a
user-observable path (a new route file that now auto-exempts). Neither
shape would fail any other test — the script is pure bash, the regex
is unparsed data, and the behaviour is only observable at PR time.

**Pin:** `tests/test_check_demo_allowlist.py`

### Exemption acceptance requires a matching diff hash

When a branch ships `docs/demos/<branch>/exemption.md` instead of a
real `demo.md`, `scripts/check-demo.sh` hashes the current
`git diff $MERGE_BASE HEAD -- . ':(exclude)docs/demos/'` and compares
against the `diff_hash` stored in the exemption's YAML frontmatter.
The pathspec exclude of `docs/demos/` is load-bearing — without it,
committing the exemption.md itself shifts the diff bytes and
invalidates its own pin. All three hash-computation sites (the
`demo-classifier` subagent, the `cloglog:demo` skill's Step 1, and
this gate script) must use the same exclude or the hashes won't
match. A mismatch means the agent classified an older diff and kept
coding — the exemption no longer covers what's shipping, so the gate
must fail. Silent-failure shapes the pin guards: a frontmatter parser
that picks up a `diff_hash:` line outside the YAML fence (e.g., in
the reasoning body) and silently accepts a stale exemption; a hash
computation that drops the `docs/demos/` exclude so every exemption
fails its own pin on first commit; a hash computation that diverges
from the classifier's convention so every stored hash either always
matches or never does; a missing `diff_hash:` silently treated as
match. If both `demo.md` and `exemption.md` exist, `demo.md` wins —
the spec is explicit on this precedence and the test locks it in.

**Pin:** `tests/test_check_demo_exemption_hash.py`

## SKILLs that touch GitHub

### No persistent bot-token origin URL in close-wave / reconcile / github-bot SKILLs

The three SKILLs that push to GitHub (close-wave Step 13, reconcile
Step 5, github-bot Push + Create) MUST push via inline URL —
`git push "https://x-access-token:${BOT_TOKEN}@github.com/${REPO}.git" "HEAD:${BRANCH}"`
followed by `git fetch origin "${BRANCH}"` and
`git branch --set-upstream-to=origin/${BRANCH}` — and MUST NOT
mutate `.git/config` via `git remote set-url origin "https://x-access-token:..."`.
A persistent bot-token origin URL breaks `make promote` (the `prod`
ruleset rejects bot pushes), strands an expired token in
`.git/config` after ~1h, and leaks the credential through
`git remote -v`. Silent-failure shape: a future PR edits a SKILL
in isolation, reintroduces the `set-url` mutation, and `ci.yml`'s
`paths:` filter excludes `plugins/**` so the regression ships
green. The pin is wired into `make invariants` AND the every-PR
`init-smoke.yml` workflow so a SKILL-only edit cannot bypass it.

**Pin:** `tests/plugins/test_skills_no_remote_set_url.py`

## Notifications

### Desktop toasts fire only for operator-attention events

The `TASK_STATUS_CHANGED → review` transition still creates the persisted
`Notification` row + dashboard bell, but **not** a `notify-send` desktop
toast. With parallel worktrees, every PR-opened toast trained the operator
to ignore them. T-358 codifies two rules: (1) `TASK_STATUS_CHANGED → review`
does not toast; (2) `AGENT_UNREGISTERED` toasts only when `data.reason` is
in a known-non-clean allowlist (`force_unregistered`, `heartbeat_timeout`).
A clean unregister via the public API has no `reason` and stays silent —
that filter keeps a normal post-merge agent exit from toasting. The
`desktop_toast_enabled: false` switch in `.cloglog/config.yaml` is the
operator off-switch (the persisted row + SSE for the review transition
are unaffected).

**Pins:**
- `tests/gateway/test_notification_listener_does_not_toast_on_review_transition.py`
- `tests/gateway/test_notification_listener_toasts_on_unregister_filter.py`

## Review engine

### `post_review` stamps `commit_id` from `head_sha`

`post_review` MUST pass `"commit_id": head_sha` in the GitHub create-review
POST. Omitted, GitHub stamps the review against the branch head at the time
the POST lands — so a push that races the review write attributes it to a
different SHA than the one codex actually inspected. Downstream
`count_bot_reviews` dedupes by `commit_id` and `_codex_passed_for_head`
filters by `commit_id == head_sha`; both silently mis-count without the
stamp. The `ReviewLoop` happy path AND the degraded single-turn path
(`session_factory is None`) BOTH need `head_sha` plumbed through. T-365.

**Pins:**
- `tests/gateway/test_review_engine.py::TestPostReview::test_commit_id_included_when_head_sha_provided`
- `tests/gateway/test_review_engine.py::TestPostReview::test_commit_id_omitted_when_head_sha_empty`
- `tests/gateway/test_review_engine.py::TestFullFlowIntegration::test_degraded_path_includes_commit_id`

### Opencode-only host must not call `count_bot_reviews`

When `_codex_available=False`, `count_bot_reviews` MUST NOT be called. Any
future code that needs a prior session count must gate the HTTP call on
`_codex_available` or pre-seed `prior = 0` before the capability-gated
block.

**Pin:** `tests/gateway/test_review_engine_t248.py::TestOpencodeOnlyHost::test_session_cap_check_skipped_when_codex_unavailable`

## EventBus / cross-worker

### Postgres `NOTIFY` echoes back to the publishing connection

Any cross-process pub/sub layered on `LISTEN`/`NOTIFY` must dedupe by a
per-process `source_id` embedded in the payload — otherwise the publisher
sees every event twice (local fan-out + LISTEN echo).

**Pin:** `tests/shared/test_event_bus_cross_worker.py::test_publisher_does_not_double_deliver_its_own_notify_echo`

### Mirrored events go to project subscribers only

Cross-worker mirrors must distinguish project subscribers from
`subscribe_all()` (global) subscribers. A global consumer that does
write-side work (e.g. `notification_listener` inserting a row) runs on
every gunicorn worker. Mirrored events go to project subscribers only;
the originating worker handles global delivery via local fan-out.
Otherwise N workers do the same write for one logical event.

**Pin:** `tests/shared/test_event_bus_cross_worker.py::test_mirrored_events_do_not_reach_global_subscribers`

### `NOTIFY` payload caps at 8000 bytes

Larger payloads silently drop at the wire. Cross-worker mirrors must
size-check client-side, log WARN, and keep local fan-out — degraded
delivery beats raising on the publish path.

**Pin:** `tests/shared/test_event_bus_cross_worker.py::test_oversize_payload_is_dropped_locally_logged_no_crash`

## Plugin: MCP server registration

### Project-scoped MCP servers live in `.mcp.json`, not `.claude/settings.json`

Claude Code's MCP loader only reads project-scoped `mcpServers` from
`.mcp.json` at repo root. `mcpServers` placed under `.claude/settings.json`
is silently ignored — the server never starts, `mcp__*` tools never
resolve, and `/cloglog setup` fails with `register_agent doesn't exist`.
Generalises beyond cloglog: any plugin that registers an MCP server for a
downstream project must write to `.mcp.json`.

**Pin:** `tests/plugins/test_init_on_fresh_repo.py::test_step3_block_writes_settings_with_no_placeholders`

### Config migration preserves sibling MCP entries

When moving config between files (e.g. T-344 hoisting `mcpServers.cloglog`
from settings.json into `.mcp.json`), pop only the migrated subkey, not
the parent map — operators hand-maintain sibling entries (`github`,
`linear`, etc.). Drop the parent only if empty.

**Pin:** `tests/plugins/test_init_on_fresh_repo.py::test_step3_migration_preserves_non_cloglog_mcp_servers`

## Workflow templating

### Worktree agents tail the worktree inbox, write supervisor events to the project root inbox

The two inbox paths are distinct and load-bearing. Tail the **worktree**
inbox (`<WORKTREE_PATH>/.cloglog/inbox`) — the backend webhook fan-out
delivers `review_submitted` / `pr_merged` / `ci_failed` / operator messages
there. Write lifecycle events (`agent_started`,
`pr_merged_notification`, `agent_unregistered`, `mcp_unavailable`,
`mcp_tool_error`) to the **project root** inbox
(`<PROJECT_ROOT>/.cloglog/inbox`) — the supervisor watches that.
Collapsing the two paths to one absolute path is the antipattern (the
2026-04-30 incident: three agents told to tail the project root inbox sat
idle for 25 minutes through operator retries).

**Pin:** `tests/plugins/test_agent_prompt_template_correct_inbox_paths.py`

### Plugin source loads live in worktree agents — no install-time cache

The launch SKILL renders `launch.sh` to spawn `claude --dangerously-skip-permissions`. That invocation MUST also pass `--plugin-dir <worktree>/plugins/cloglog` so claude resolves the cloglog plugin from the worktree's on-disk source on every launch. Without the flag, claude falls back to its install-time plugin cache (populated by `claude plugins install`), and edits to `plugins/cloglog/skills/**`, `hooks/**`, or `templates/**` made in the worktree are silently invisible to the spawned agent — the cache freezes the plugin contents at install time, so a SKILL fix only takes effect after the operator manually reinstalls. This is a silent failure: the agent runs against stale plugin code with no diagnostic, no error, and no test catches it because the renderer still passes `bash -n`. The path must be absolute and rooted at THIS worktree's plugin copy (each worktree carries its own), not a shared install — the per-worktree path is what makes plugin edits in branch X invisible to a parallel agent in branch Y, which is the desired isolation.

**Pin:** `tests/plugins/test_launch_sh_loads_plugin_live.py`

### `launch.sh` heredoc renders cleanly

The launch SKILL emits `.cloglog/launch.sh` via a heredoc. Use the
**quoted** delimiter (`<< 'EOF'`) so bash performs zero expansion inside,
then substitute operator-host paths via post-render `sed -i
"s|@@WORKTREE_PATH@@|...|g"`. Unquoted heredocs combined with `\$N`
positional refs collapse inconsistently across the SKILL → Bash-tool →
bash boundary (T-353 antisocial: rendered launch.sh contained `local
file="\"; local key="\""` and tripped `unexpected EOF while looking for
matching '"'` at exec time, so the spawned tab silently failed and no
`agent_started` event ever fired).

**Pin:** `tests/plugins/test_launch_skill_renders_clean_launch_sh.py`

### Agents must echo `agent_started` and the supervisor must enforce a deadline

`agent_started` is the only authoritative liveness signal — a spawned
zellij tab proves nothing about the claude session inside it. The main
agent must wait up to `launch_confirm_timeout_seconds` (default 90 s, in
`.cloglog/config.yaml`) for `agent_started` per spawned worktree, then
hand off to the operator with a probe checklist instead of silently
retrying. Same deadline applies to supervisor relaunches between tasks.
T-356.

**Pin:** `tests/plugins/test_launch_skill_has_agent_started_timeout.py`

### Zellij tab teardown must go through `close-zellij-tab.sh`

`zellij action close-tab` takes no positional argument and closes the
*focused* tab — not the named one. Pairing `query-tab-names` with a bare
`close-tab` killed the supervisor's own tab twice in production (T-339).
All teardown call sites (`close-wave` Step 5c, `reconcile` teardown,
`worktree-remove.sh`) MUST route through
`plugins/cloglog/hooks/lib/close-zellij-tab.sh`, which resolves the
target by name, refuses (exit 2) when the resolved target equals the
focused tab id, and only then issues a `--tab-id`-scoped close. Callers
must surface exit 2 as a hard error, never fall back to a bare
`close-tab`.

**Pin:** `tests/plugins/test_close_tab_safety.py`
