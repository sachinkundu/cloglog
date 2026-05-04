# cloglog credentials

The cloglog MCP server authenticates to the backend with a single
**project API key** (`CLOGLOG_API_KEY`). The key is project-level — every
worktree under the same project shares it — and it must live **outside any
per-worktree file**, because anything inside a worktree is reachable by
tooling that bypasses MCP.

This is the operator-facing setup doc for that key. It is referenced from
`mcp-server/src/credentials.ts` (the loader) and from the worktree-create
warning emitted when the credentials cannot be located.

## Resolution order

The MCP server (`mcp-server/dist/index.js`) and the worktree-launch
`_api_key` helper (`plugins/cloglog/skills/launch/SKILL.md`) resolve the key
at startup, in this order (T-382 — per-project resolution so multi-project
hosts don't send the wrong project's key):

1. **`CLOGLOG_API_KEY` in the launching process's environment.**
   Convenient for local dev: export it in your shell rc (`~/.bashrc`,
   `~/.zshrc`) or in the systemd / launchd unit that starts Claude Code.

2. **`~/.cloglog/credentials.d/<project_slug>`** — a per-project `KEY=VALUE`
   file. The slug comes from `<project_root>/.cloglog/config.yaml: project`
   with a `basename($PROJECT_ROOT)` fallback. The MCP server walks up from
   `process.cwd()` until it finds `.cloglog/config.yaml`, so the lookup
   works the same whether the server is started from the project root or
   from a worktree subdir. Slugs must match `[A-Za-z0-9._-]+` — anything
   else is rejected (no path traversal).

3. **`~/.cloglog/credentials`** — a single `KEY=VALUE` file. This is the
   legacy single-project location and is still consulted as the final
   fallback. Hosts with one project keep working unchanged.

Files in either location must be mode `0600`; anything looser earns a
warning on stderr (the file is still read).

If none of the three sources yield a non-empty key, the MCP server prints a
multi-line diagnostic to stderr (naming every path it tried, including the
per-project path with its derived slug) and exits with status `78`
(`EX_CONFIG`). Claude Code's MCP loader will then mark the server as
failed; agents inside the worktree will see no `mcp__cloglog__*` tools at
startup.

> **Multi-project hosts.** When you run cloglog and other cloglog-managed
> projects on the same machine, prefer the per-project files. The shared
> backend mints one project-scoped API key per project via
> `POST /api/v1/projects`; each project gets its own
> `~/.cloglog/credentials.d/<slug>` so the right key is sent for the right
> project, even though every project authenticates against the same backend
> URL. Before T-382 the legacy global file held one key, so calls from the
> other projects' worktrees produced silent 401/403 on
> `/api/v1/agents/unregister-by-path` and similar agent-side endpoints
> (the backend's project-scoped auth rejects a key that doesn't match the
> project the worktree belongs to) — the failure that motivated this change.

## First-time setup — new project via `/cloglog init`

If you are adding a **new project** to an existing cloglog backend, the
easiest path is:

```
/cloglog init
```

The init skill's **Step 2** detects that `.cloglog/config.yaml` has no `project_id`
and runs a two-phase bootstrap:

1. **Phase 1 (pre-MCP):** calls `POST /api/v1/projects` directly against
   the backend using your `DASHBOARD_SECRET`. It creates the project,
   writes the returned API key to `~/.cloglog/credentials.d/<project_slug>`
   (T-398: always per-project — `project_id` is seeded into
   `.cloglog/config.yaml` and the strict-fallback guard rejects the legacy
   global file when `project_id` is set), then asks you to restart Claude Code.

2. **Phase 2 (post-restart):** on the second `/cloglog init` run the MCP
   server finds the per-project credentials and `project_id` is already in
   `.cloglog/config.yaml`, so the bootstrap is skipped and the remaining
   setup steps (MCP config, `.cloglog/`, CLAUDE.md, GitHub bot) complete
   via MCP tools.

**Prerequisite:** the init skill reads the dashboard key from `$DASHBOARD_SECRET`
(the same variable your backend's `.env` sets). Export it in your shell RC
(`~/.bashrc`, `~/.zshenv`) so the init skill can read it without prompting:

```bash
export DASHBOARD_SECRET=<value from your backend's DASHBOARD_SECRET setting>
```

## First-time setup — manual

If you need to create the project manually (e.g. scripted provisioning):

```bash
# 1. Create the project and capture the API key (shown once)
BACKEND_URL="${CLOGLOG_BACKEND_URL:-http://127.0.0.1:8001}"
RESPONSE=$(curl -sf -X POST \
  -H "Content-Type: application/json" \
  -H "X-Dashboard-Key: ${DASHBOARD_SECRET}" \
  -d '{"name": "my-project", "description": ""}' \
  "${BACKEND_URL}/api/v1/projects")

API_KEY=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['api_key'])")
PROJECT_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")

# 2. Derive a slug-safe identifier from the backend project name, validated
#    the same way the resolver expects ([A-Za-z0-9._-]+). The slug is what
#    the per-project file is named under and what `project:` carries in
#    .cloglog/config.yaml — backend names are unconstrained free-form
#    strings (e.g. "My Project") so they MUST be slugified before use.
PROJECT_NAME="my-project"
PROJECT_SLUG=$(printf '%s' "$PROJECT_NAME" | tr -c '[:alnum:]._-' '-' | sed 's/^-*//; s/-*$//')
if [ -z "$PROJECT_SLUG" ]; then
  PROJECT_SLUG=$(basename "$(pwd)" | tr -c '[:alnum:]._-' '-' | sed 's/^-*//; s/-*$//')
fi
[ -z "$PROJECT_SLUG" ] && { echo "ERROR: cannot derive a slug-safe identifier" >&2; exit 1; }

# 3. Store credentials. T-398: always write to ~/.cloglog/credentials.d/<slug>
#    regardless of whether other projects exist on this host. After bootstrap
#    .cloglog/config.yaml carries project_id, and the strict-fallback guard in
#    loadApiKey rejects the legacy global file when project_id is set.
mkdir -p ~/.cloglog/credentials.d
printf 'CLOGLOG_API_KEY=%s\n' "$API_KEY" > ~/.cloglog/credentials.d/"$PROJECT_SLUG"
chmod 600 ~/.cloglog/credentials.d/"$PROJECT_SLUG"

# 4. Store project, project_id, and backend_url (T-382: persist `project:`
#    so the per-project resolver finds the slug source on first restart;
#    without it the resolver falls back to basename($PROJECT_ROOT) and
#    misses the credentials.d/<slug> file we just wrote). Update in place
#    if already present; append if not. Never use >> alone — the scalar
#    parser reads the first matching key, so a duplicate line silently
#    shadows the new value on re-runs.
mkdir -p .cloglog
if [ -f .cloglog/config.yaml ] && grep -q '^project:' .cloglog/config.yaml; then
  sed -i "s/^project:.*/project: ${PROJECT_SLUG}/" .cloglog/config.yaml
else
  printf 'project: %s\n' "$PROJECT_SLUG" >> .cloglog/config.yaml
fi
if [ -f .cloglog/config.yaml ] && grep -q '^project_id:' .cloglog/config.yaml; then
  sed -i "s/^project_id:.*/project_id: ${PROJECT_ID}/" .cloglog/config.yaml
else
  printf 'project_id: %s\n' "$PROJECT_ID" >> .cloglog/config.yaml
fi
if [ -f .cloglog/config.yaml ] && grep -q '^backend_url:' .cloglog/config.yaml; then
  sed -i "s|^backend_url:.*|backend_url: ${BACKEND_URL}|" .cloglog/config.yaml
else
  printf 'backend_url: %s\n' "$BACKEND_URL" >> .cloglog/config.yaml
fi
```

Store the key in your password manager; the backend keeps only a SHA-256
hash and cannot show it again. You can rotate it at any time with
`scripts/rotate-project-key.py`.

## Migration from the old `.mcp.json` layout

Before T-214 the key lived in `.mcp.json` under `mcpServers.cloglog.env`.
After T-214, that line is removed from the committed `.mcp.json` and from
the worktree-create hook. To migrate an existing checkout:

```bash
# Pull the key out of the old .mcp.json once, then write it to the new home.
# T-382: pick single-project (legacy global) vs multi-project
# (credentials.d/<slug>) destination based on whether ~/.cloglog/credentials
# is already in use by another project.
old_key=$(python3 -c "
import json, pathlib
p = pathlib.Path('.mcp.json')
print(json.loads(p.read_text()).get('mcpServers', {}).get('cloglog', {}).get('env', {}).get('CLOGLOG_API_KEY', ''))
")
if [ -n "$old_key" ]; then
  # T-398: always write to credentials.d/<slug>. After bootstrap .cloglog/config.yaml
  # carries project_id, and the strict-fallback guard rejects the legacy global file
  # when project_id is set. Writing to ~/.cloglog/credentials would cause a startup
  # failure on the next MCP server launch.
  SLUG=$(grep '^project:' .cloglog/config.yaml 2>/dev/null | head -n1 \
          | sed 's/^project:[[:space:]]*//; s/[[:space:]]*#.*$//' \
          | tr -d '"'"'")
  if [ -z "$SLUG" ] || ! [[ "$SLUG" =~ ^[A-Za-z0-9._-]+$ ]]; then
    SLUG=$(basename "$(pwd)" | tr -c '[:alnum:]._-' '-' | sed 's/^-*//; s/-*$//')
  fi
  [ -z "$SLUG" ] && { echo "ERROR: cannot derive slug for credentials.d/<slug>"; exit 1; }
  mkdir -p ~/.cloglog/credentials.d
  printf 'CLOGLOG_API_KEY=%s\n' "$old_key" > ~/.cloglog/credentials.d/"$SLUG"
  chmod 600 ~/.cloglog/credentials.d/"$SLUG"
fi
```

After the move, run `git pull` (or rebase your local edits onto the merged
T-214 change) so the working `.mcp.json` no longer has the key.

## Production / `make promote`

The same files apply on the production host. After `make promote` (or any
fresh deploy of the backend + MCP server), check that
`~/.cloglog/credentials.d/<project_slug>` exists for the user that runs the
supervisor session. T-398: once `.cloglog/config.yaml` carries `project_id`
(which it always does after bootstrap), the MCP server rejects the legacy
`~/.cloglog/credentials` at startup and requires the per-project file. If the
per-project file is absent, agents launched on that host will fail to register.

## Operational notes

- **Rotation.** `scripts/rotate-project-key.py` rotates the key in the
  database. Then replace the `CLOGLOG_API_KEY=` line in
  `~/.cloglog/credentials.d/<project_slug>`. The slug is the value of
  `project:` in this repo's `.cloglog/config.yaml`. T-398: the legacy
  `~/.cloglog/credentials` is not read when `project_id` is set, so
  updating it has no effect on the MCP server.
  Repeat on every host that has an MCP server (dev workstation, prod,
  any alt-checkout) — the loader does not watch the file, so each MCP
  server picks up the new key on its next start. **Stale per-project
  files block fallback (T-382 fail-loud invariant): rotating the key
  but forgetting to update `credentials.d/<slug>` will leave the MCP
  server starting up against the OLD key (or refusing to start if the
  file is now blank).** Restart Claude Code after every rotation so the
  refresh actually takes effect.
- **Permissions.** `chmod 600` is checked best-effort by the loader on
  every file it reads (legacy global AND each `credentials.d/<slug>`);
  looser modes log a warning to stderr but do not block startup.
  Tighten them.
- **Ignored locations.** The loader does **not** read `.env`, the
  worktree's `.mcp.json`, the repo-root `.mcp.json`, or any other
  per-worktree file. The hooks
  (`plugins/cloglog/hooks/worktree-create.sh`,
  `plugins/cloglog/hooks/agent-shutdown.sh`) match the MCP server's
  resolution exactly via the shared helper at
  `plugins/cloglog/hooks/lib/resolve-api-key.sh`: env →
  `~/.cloglog/credentials.d/<slug>` → `~/.cloglog/credentials`. This is
  intentional — see T-214 for the per-worktree exclusion and T-382 for
  the per-project layer.

## Related

- `mcp-server/src/credentials.ts` — the loader.
- `mcp-server/tests/credentials.test.ts` — coverage for the loader.
- `tests/test_mcp_json_no_secret.py` — regression guard against the key
  ever returning to `.mcp.json`.
- `${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md` §4 (MCP discipline) — the broader rule
  this credential location enforces.
- `docs/postmortems/2026-04-10-mcp-registration-auth.md` — the original
  incident that introduced the key into `.mcp.json`; T-214 closes the
  follow-up.

## GitHub reviewer bots — different credential path

Reviewer bots (codex, opencode) do **not** use `~/.cloglog/credentials`. They
are full GitHub Apps and mint short-lived installation tokens from PEM files
under `~/.agent-vm/credentials/`:

| Bot | PEM path | App-id / installation-id |
|-----|----------|--------------------------|
| `sakundu-claude-assistant[bot]` (code-push bot) | `~/.agent-vm/credentials/github-app.pem` | hard-coded in `src/gateway/github_token.py`; **agent-side minting** by `gh-app-token.py` resolves `GH_APP_ID` / `GH_APP_INSTALLATION_ID` from env → `.cloglog/local.yaml` (gitignored) → `.cloglog/config.yaml` (T-348 — see below) |
| `cloglog-codex-reviewer[bot]` | `~/.agent-vm/credentials/codex-reviewer.pem` | hard-coded in `src/gateway/github_token.py` |
| `cloglog-opencode-reviewer[bot]` (**T-248**) | `~/.agent-vm/credentials/opencode-reviewer.pem` | hard-coded in `src/gateway/github_token.py` (`_OPENCODE_APP_ID`, `_OPENCODE_INSTALLATION_ID`) |

App IDs and installation IDs are **not secrets** — they are public
identifiers and live as module-level constants in
`src/gateway/github_token.py` alongside `_CLAUDE_APP_ID` and
`_CODEX_APP_ID`. Do NOT set `OPENCODE_APP_ID` / `OPENCODE_INSTALLATION_ID`
as env vars expecting the backend to read them; `github_token.py` never
consults env for reviewer App IDs, so env-based tweaks are silently
ignored. Only the PEM is per-host.

### Code-push bot — config-driven token minting (T-314, T-348)

The plugin skill script `plugins/cloglog/scripts/gh-app-token.py` is used by
worktree agents to mint short-lived tokens at runtime; it reads
`GH_APP_ID` / `GH_APP_INSTALLATION_ID` from the **exported environment** so
it can be reused in other projects without embedding any one operator's
identifiers.

**Required in `.cloglog/local.yaml` (T-348, gitignored — preferred):**

```yaml
gh_app_id: "<your-app-id>"
gh_app_installation_id: "<your-installation-id>"
```

`.cloglog/local.yaml` is gitignored because each operator installs the
App into their own org/repo and gets a distinct Installation ID — committing
these would push other clones at the wrong installation. `gh-app-token.py`
resolves both keys itself in this order: env → `.cloglog/local.yaml` →
`.cloglog/config.yaml` (tracked fallback for single-operator repos). The
launch skill *also* exports them into worktree-agent shells so they survive
`/clear` between tasks (T-329) for downstream `gh` calls that use the env
directly.

**Optional shell-RC fallback** (for ad-hoc `gh-app-token.py` invocations
outside the worktree-launch path — e.g. running `make verify-prod-protection`
in your interactive shell): export `GH_APP_ID` / `GH_APP_INSTALLATION_ID`
in `~/.bashrc`, `~/.zshenv`, `~/.profile`, or via [direnv](https://direnv.net/).

Verify after launching a worktree agent (or in your shell, if using the RC
path) with:

```bash
printenv GH_APP_ID GH_APP_INSTALLATION_ID
```

`scripts/preflight.sh` warns when neither path resolves the values. If
both are absent, any skill command that runs
`plugins/cloglog/scripts/gh-app-token.py` (github-bot, close-wave,
reconcile) will exit with `Error: GH_APP_ID is required (env or
.cloglog/local.yaml)`.

**Each operator's own values are stored in their own gitignored
`.cloglog/local.yaml`.** Never copy these between operators or commit them
to `.cloglog/config.yaml` — that would push other clones at the wrong App
installation. The PEM is the only host-local secret; the App and
Installation IDs are non-secret but still per-operator.

Onboarding a new host:

1. Download the code-push bot's private key (`.pem`) from the GitHub App
   settings.
2. `chmod 600` it and place it at
   `~/.agent-vm/credentials/github-app.pem`.

If this PEM is missing, `plugins/cloglog/scripts/gh-app-token.py` exits
non-zero with `Error: PEM file not found at ~/.agent-vm/credentials/github-app.pem`
and every agent push / PR-create operation fails. `~/.cloglog/credentials`
is NOT consulted for code-push tokens; do not place PEM contents there.

## Opencode reviewer — enable flag

Stage A (opencode) is gated on the `OPENCODE_ENABLED` environment variable
(`settings.opencode_enabled`, T-275). **Default is `false`** because the
stock reviewer model (`gemma4-e4b-32k`) rubber-stamps `:pass:` regardless of
diff content, so running stage A under the default model produces noise, not
signal. Stage B (codex) runs unaffected; on a codex + opencode host, leaving
the flag off just means "codex-only review."

**Opencode-only hosts** (no `codex` binary on PATH) **must** set
`OPENCODE_ENABLED=true`. Otherwise `app.py`'s registration gate evaluates
`codex_ok or opencode_effective == False`, the consumer is NOT registered,
and PR webhooks fall on the floor — a loud ERROR is logged at boot naming
the three inputs (`codex_available`, `opencode_available`,
`opencode_enabled`). Flip the flag once T-274's agentic-mode work lands a
reviewer model that defends severity.

```
# .env on an opencode-only host — REQUIRED to re-enable stage A.
OPENCODE_ENABLED=true
```

## Opencode reviewer — ollama model + VRAM setup

Default model: **`ollama/gemma4-e4b-32k`** (see
`src/shared/config.py::Settings.opencode_model`). This is a 32K-context
variant of `gemma4:e4b` that keeps the whole model + KV cache under 12 GB
so it runs **100% on GPU** on a 24 GB card. Measured latency on an RTX
4090 with no other VRAM tenants: **~15 s / turn** for a typical PR.

The 32K variant is a **per-host setup step**, not a repo artifact — each
review host rebuilds it once via `ollama create`:

```bash
# One-time: build the 32K-context variant from stock gemma4:e4b.
cat <<'MODELFILE' | ollama create gemma4-e4b-32k -f /dev/stdin
FROM gemma4:e4b
PARAMETER num_ctx 32768
MODELFILE

# Register with opencode so `--model ollama/gemma4-e4b-32k` resolves.
# Edit ~/.config/opencode/opencode.json, add under provider.ollama.models:
#   "gemma4-e4b-32k": { "name": "Gemma 4 E4B (32K, reviewer)" }
```

To use a different model or context size, override `OPENCODE_MODEL` in
`.env` and create the corresponding ollama variant.

### VRAM pressure — competing tenants

The stock `gemma4:e4b` ships with `num_ctx=131072`. At that context, the
KV cache balloons to ~16 GB and the model spills to CPU — one review turn
stretches past 10 minutes of CPU-offloaded inference, unusable for the
5-turn stage-A loop. The 32K variant above caps the KV cache at ~2 GB.

**On the development host, do not run ComfyUI (or any ~16 GB VRAM tenant)
concurrently with the review engine.** ComfyUI holds loaded diffusion
models in VRAM between workflow runs; if it's active, the reviewer model
CPU-offloads despite the 32K cap. Observed behaviour: with ComfyUI active
and only ~4 GB free VRAM, `ollama ps` reports ~66% CPU / ~34% GPU and the
turn exceeds the 240 s timeout.

The `nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv`
command at boot time identifies who's holding VRAM.

### Tuning the turn timeout

`opencode_turn_timeout_seconds` defaults to **240 s** — a ~16× headroom
over the measured ~15 s/turn. If your host consistently sees GPU-only
latencies under 60 s, you can lower it in `.env`:

```
OPENCODE_TURN_TIMEOUT_SECONDS=60
```

If you see timeouts in the per-turn log lines, check `ollama ps` — any
`CPU/GPU` split is a sign of VRAM pressure; fix the environment rather
than raising the timeout.
