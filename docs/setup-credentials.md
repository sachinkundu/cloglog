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

The MCP server (`mcp-server/dist/index.js`) resolves the key at startup, in
this order:

1. **`CLOGLOG_API_KEY` in the launching process's environment.**
   Convenient for local dev: export it in your shell rc (`~/.bashrc`,
   `~/.zshrc`) or in the systemd / launchd unit that starts Claude Code.

2. **`~/.cloglog/credentials`.** A `KEY=VALUE` file containing at least
   `CLOGLOG_API_KEY=<key>`. Mode **must** be `0600`; anything looser earns a
   warning on stderr (the file is still read).

If neither source yields a non-empty key, the MCP server prints a multi-line
diagnostic to stderr and exits with status `78` (`EX_CONFIG`). Claude Code's
MCP loader will then mark the server as failed; agents inside the worktree
will see no `mcp__cloglog__*` tools at startup.

## First-time setup

```bash
mkdir -p ~/.cloglog
printf 'CLOGLOG_API_KEY=<your-project-key>\n' > ~/.cloglog/credentials
chmod 600 ~/.cloglog/credentials
```

Get the project key via `scripts/rotate-project-key.py` — it prints the
plaintext key once after rotation. Store the key in your password manager;
the backend keeps only a SHA-256 hash, so it cannot show it again.

## Migration from the old `.mcp.json` layout

Before T-214 the key lived in `.mcp.json` under `mcpServers.cloglog.env`.
After T-214, that line is removed from the committed `.mcp.json` and from
the worktree-create hook. To migrate an existing checkout:

```bash
# Pull the key out of the old .mcp.json once, then write it to the new home.
old_key=$(python3 -c "
import json, pathlib
p = pathlib.Path('.mcp.json')
print(json.loads(p.read_text()).get('mcpServers', {}).get('cloglog', {}).get('env', {}).get('CLOGLOG_API_KEY', ''))
")
if [ -n "$old_key" ]; then
  mkdir -p ~/.cloglog
  printf 'CLOGLOG_API_KEY=%s\n' "$old_key" > ~/.cloglog/credentials
  chmod 600 ~/.cloglog/credentials
fi
```

After the move, run `git pull` (or rebase your local edits onto the merged
T-214 change) so the working `.mcp.json` no longer has the key.

## Production / `make promote`

The same file applies on the production host. After `make promote` (or any
fresh deploy of the backend + MCP server), check that
`~/.cloglog/credentials` exists for the user that runs the supervisor
session. If it does not, agents launched on that host will fail to register.

## Operational notes

- **Rotation.** `scripts/rotate-project-key.py` rotates the key in the
  database. Replace the `CLOGLOG_API_KEY=` line in `~/.cloglog/credentials`
  on every host that has an MCP server (dev workstation, prod, any
  alt-checkout) — the loader does not watch the file, so each MCP server
  picks up the new key on its next start.
- **Permissions.** `chmod 600` is checked best-effort by the loader; looser
  modes log a warning to stderr but do not block startup. Tighten them.
- **Ignored locations.** The loader does **not** read `.env`, the
  worktree's `.mcp.json`, the repo-root `.mcp.json`, or any other
  per-worktree file. The hooks (`plugins/cloglog/hooks/worktree-create.sh`,
  `plugins/cloglog/hooks/agent-shutdown.sh`) match: they accept env or
  `~/.cloglog/credentials` only. This is intentional — see T-214.

## Related

- `mcp-server/src/credentials.ts` — the loader.
- `mcp-server/tests/credentials.test.ts` — coverage for the loader.
- `tests/test_mcp_json_no_secret.py` — regression guard against the key
  ever returning to `.mcp.json`.
- `docs/design/agent-lifecycle.md` §4 (MCP discipline) — the broader rule
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
| `sakundu-claude-assistant[bot]` (code-push bot) | `~/.agent-vm/credentials/github-app.pem` | hard-coded in `src/gateway/github_token.py` |
| `cloglog-codex-reviewer[bot]` | `~/.agent-vm/credentials/codex-reviewer.pem` | hard-coded in `src/gateway/github_token.py` |
| `cloglog-opencode-reviewer[bot]` (**T-248**) | `~/.agent-vm/credentials/opencode-reviewer.pem` | read from `OPENCODE_APP_ID` / `OPENCODE_INSTALLATION_ID` env vars |

Onboarding the opencode reviewer bot on a new host:

1. Install the GitHub App on the target repo(s).
2. Download the App's private key (a `.pem` file).
3. Place it at `~/.agent-vm/credentials/opencode-reviewer.pem` and
   `chmod 600` it.
4. Export `OPENCODE_APP_ID` and `OPENCODE_INSTALLATION_ID` in the backend's
   environment (the backend's `.env` is fine) with the values from the
   GitHub App settings.

If either env var is empty the sequencer logs one INFO line per session and
falls through to codex-only — the backend still boots healthy.
`~/.cloglog/credentials` is NOT consulted for reviewer tokens; do not place
PEM contents there.
