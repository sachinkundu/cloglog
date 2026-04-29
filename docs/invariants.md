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
