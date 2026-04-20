# F-48 Agent Lifecycle Hardening — Manual Test Guide

_Status 2026-04-20. Covers Wave A (spec) and Wave B (five behavioural fixes).
Wave C and beyond are listed at the bottom under **Not yet shipped**._

F-48 is the umbrella feature "Agent Lifecycle Hardening — Graceful Shutdown &
MCP Discipline". Six tasks have merged so far, across four PRs:

| Task | Scope | Shipped in |
|------|-------|------------|
| T-222 | Canonical agent-lifecycle protocol doc (single source of truth) | PR #152 → `docs/design/agent-lifecycle.md` |
| T-215 | Backend `request_shutdown` writes to `<worktree_path>/.cloglog/inbox` instead of a dead `/tmp` path | PR #166 |
| T-214 | Stop shipping `CLOGLOG_API_KEY` inside worktree `.mcp.json`; resolve from env or `~/.cloglog/credentials` | PR #168 |
| T-217 | Agent-shutdown hook fires reliably on TERM/HUP via launcher-wrapper trap | PR #167 |
| T-219 | `prefer-mcp.sh` blocks loopback aliases and every major HTTP client (no more keyword-allowlist bypass) | PR #167 |
| T-242 | Fresh worktrees start with an empty `shutdown-artifacts/` (dir reset on bootstrap, files now gitignored) | PR #167 |

Every Wave-B delta also has a showboat-verifiable proof-of-work demo under
`docs/demos/`. Run all three with `uvx showboat verify docs/demos/<branch>/demo.md`
for a byte-exact replay. The walk-throughs below are lower-ceremony checks an
operator can run from a clean shell.

---

## Prerequisites

One-time host setup (prod and dev workstations both need this):

```bash
mkdir -p ~/.cloglog
# Use the real key; rotate via scripts/rotate-project-key.py if you've lost it.
printf 'CLOGLOG_API_KEY=%s\n' "$YOUR_PROJECT_KEY" > ~/.cloglog/credentials
chmod 600 ~/.cloglog/credentials
```

All other tests assume:

- You're in the repo root at `/home/sachin/code/cloglog`.
- Backend is either already running (`make promote` flow) or you're about to
  use the read-only repo tests that don't need it.
- Dev DB is up (`make db-up`) only for live-backend tests (T-215).

---

## Wave A — T-222: Canonical lifecycle doc

Not a runtime change. It is the reference document every Wave-B task, plugin
skill, AGENT_PROMPT template, and reviewer defers to.

**Manual check.**

```bash
wc -l docs/design/agent-lifecycle.md
head -50 docs/design/agent-lifecycle.md
```

Expected: the file exists, is > 200 lines, and starts with
`# Agent Lifecycle Protocol`. The authoritative exit-condition algorithm
(Section 1) and the three-tier shutdown ladder (Section 5) are the pieces
every other task is implementing against.

There is no behavioural test for T-222 — it is the contract the rest of the
wave satisfies.

---

## Wave B — Runtime changes

### T-215 — Backend `request_shutdown` writes to the worktree inbox

**What changed.** The backend's `POST /agents/{worktree_id}/request-shutdown`
used to write to `/tmp/cloglog-inbox-{id}` — a path no agent ever monitored.
It now writes a `{"type":"shutdown",…}` JSON line to
`<worktree.worktree_path>/.cloglog/inbox`, which every worktree agent already
tails. This is the enablement for T-220's cooperative shutdown.

**Read-only repo checks.** No backend needed.

```bash
# Legacy write path is gone from src/.
grep -rn '/tmp/cloglog-inbox-' src/ | wc -l        # 0

# New canonical path is built from worktree.worktree_path.
grep -cE "Path\(worktree\.worktree_path\) / \"\.cloglog\" / \"inbox\"" src/agent/services.py    # 1

# Historical inbox the backend actually wrote during the demo run:
cat docs/demos/wt-t215-shutdown-path/captured-inbox.txt
```

Expected: `0`, `1`, and a single-line JSON whose `"type"` is `"shutdown"` and
whose `"target_worktree_id"` matches the UUID shown in the demo.

**Live end-to-end check** (requires dev backend running on `:8000`):

```bash
# 1. Create a sacrificial worktree path with an inbox dir.
WT=/tmp/demo-t215-live && rm -rf "$WT" && mkdir -p "$WT/.cloglog"
touch "$WT/.cloglog/inbox"

# 2. Register it (any project key works; this is dev DB).
KEY=$(awk -F= '/^CLOGLOG_API_KEY=/{print $2}' ~/.cloglog/credentials)
WTID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/agents/register \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d "{\"worktree_path\":\"$WT\"}" | jq -r .worktree_id)
echo "worktree_id=$WTID"

# 3. Fire request_shutdown.
curl -s -X POST "http://127.0.0.1:8000/api/v1/agents/$WTID/request-shutdown" \
  -H "Authorization: Bearer $KEY"

# 4. Expected result: one JSON line in the worktree inbox.
cat "$WT/.cloglog/inbox"
```

Expected: the file contains a line like
`{"type":"shutdown","target_worktree_id":"...","message":"..."}` — and
**no** file was created under `/tmp/cloglog-inbox-*`.

---

### T-214 — `CLOGLOG_API_KEY` leaves `.mcp.json`

**What changed.** `.mcp.json` used to put the project API key in plaintext
under `mcpServers.cloglog.env.CLOGLOG_API_KEY`. Every worktree that cloned the
repo inherited it — meaning any process inside the worktree could curl the
backend directly and bypass the MCP discipline. Now only `CLOGLOG_URL` is in
the env block. The MCP server resolves the key from, in order:

1. Operator environment (`$CLOGLOG_API_KEY`).
2. `~/.cloglog/credentials` (mode 0600).
3. Fail with a stderr diagnostic and `exit 78` (`EX_CONFIG`).

A Python regression guard at `tests/test_mcp_json_no_secret.py` pins the
invariant in CI.

**Repo-shape checks.**

```bash
# .mcp.json keeps only CLOGLOG_URL under env.
jq -r ".mcpServers.cloglog.env | keys[]" .mcp.json | sort
# Expected output:
#   CLOGLOG_URL

# No 64-hex key leaked elsewhere in the file.
grep -E '[0-9a-f]{64}' .mcp.json | wc -l          # 0

# Credentials file is locked down on this host.
stat -c "%a" "$HOME/.cloglog/credentials"          # 600
grep -c "^CLOGLOG_API_KEY=" "$HOME/.cloglog/credentials"   # 1

# The paranoid pytest regression still passes in isolation.
uv run pytest tests/test_mcp_json_no_secret.py -q
```

Expected: `CLOGLOG_URL` only, `0` key leaks, file is `600` with one
`CLOGLOG_API_KEY=` line, and 3/3 tests pass.

**Happy-path startup check** (requires `mcp-server/dist/index.js` built —
run `cd mcp-server && make build` if you've never built it):

```bash
# With credentials resolved, the server prints its boot line and stays alive.
timeout 2 node mcp-server/dist/index.js 2>&1 | head -3
```

Expected: one line like `cloglog-mcp: server started on stdio`. A missing
credentials file is the negative test:

```bash
# Force the resolver to fail. Server exits 78 with an actionable diagnostic.
HOME=/nonexistent CLOGLOG_API_KEY= node mcp-server/dist/index.js 2>&1; echo "exit=$?"
```

Expected: stderr mentions `/nonexistent/.cloglog/credentials`, the `chmod 600`
recipe, and `CLOGLOG_API_KEY`. Process ends with `exit=78`.

---

### T-217 — Shutdown hook actually fires on TERM/HUP

**What changed.** The launcher used to `exec claude`, which dropped any trap
in the bash wrapper before the signal ever arrived. `zellij action close-tab`
was also discovered to _not_ signal the pane's children at all — they are
reparented to zellij and keep running. The fix has two parts:

1. `plugins/cloglog/skills/launch/SKILL.md` — the launcher template now runs
   Claude as a subprocess (no `exec`) with TERM/HUP/INT traps that POST
   directly to `/agents/unregister-by-path`.
2. `plugins/cloglog/hooks/agent-shutdown.sh` — writes an **unconditional
   breadcrumb** to `/tmp/agent-shutdown-debug.log` as its very first action,
   so post-incident investigators can tell "hook never ran" from "hook ran
   and errored."

**Manual check — hook runs end-to-end.**

```bash
rm -f /tmp/agent-shutdown-debug.log
echo '{"cwd":"/tmp/does-not-exist"}' | bash plugins/cloglog/hooks/agent-shutdown.sh
echo "exit=$?"
grep -c "agent-shutdown.sh fired" /tmp/agent-shutdown-debug.log     # >= 1
head -3 /tmp/agent-shutdown-debug.log
```

Expected: `exit=0` (or `exit=1` if the worktree-resolution step can't find
the cwd — that's fine, the breadcrumb is the signal we care about), and the
debug log contains at least one `agent-shutdown.sh fired` line with a
timestamp.

**Manual check — launcher trap fires on TERM.**

```bash
rm -f /tmp/agent-shutdown-debug.log
# Strip the exec: the fix is specifically that 'exec' is gone from the template.
grep -c '^exec claude' plugins/cloglog/skills/launch/SKILL.md        # 0
# Launcher template declares the trap:
grep -cE 'trap .* TERM' plugins/cloglog/skills/launch/SKILL.md        # >= 1
```

The end-to-end signal-delivery test uses a sacrificial process; see
`docs/demos/wt-b2-hooks/demo.md` for the full shell block (runs a
fake-Claude stand-in under `sleep 300`, sends SIGTERM, verifies the trap
fires).

---

### T-219 — `prefer-mcp.sh` closes the direct-call bypasses

**What changed.** The hook used to only match `curl http://localhost:8000`
and had a wide keyword-allowlist escape hatch. It now blocks direct backend
calls across every loopback alias (`127.0.0.1`, `localhost`, `0.0.0.0`,
`[::1]`) for **curl, wget, httpie, python (urllib/httpx/requests/http.client),
and node (fetch).** The only escape hatch is an inline env flag
`CLOGLOG_ALLOW_DIRECT_API=1 <cmd>` — intended for deliberate debugging.

**Quick manual probes.** Each one calls the hook the way Claude Code does —
JSON on stdin, exit code is the decision (`0` = allow, `2` = block).

```bash
HOOK=plugins/cloglog/hooks/prefer-mcp.sh

# Should BLOCK (exit 2).
for cmd in \
  'curl http://127.0.0.1:8001/api/v1/tasks' \
  'curl http://localhost:8001/api/v1/tasks' \
  'curl http://0.0.0.0:8001/api/v1/tasks' \
  'curl -6 "http://[::1]:8001/api/v1/tasks"' \
  'wget http://127.0.0.1:8001/api/v1/tasks' \
  'http GET http://localhost:8001/api/v1/tasks' \
  'python -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8001/api/v1/tasks\")"' \
  'node -e "fetch(\"http://localhost:8001/api/v1/tasks\")"' ; do
    printf '{"tool":"Bash","input":{"command":%s}}' "$(jq -Rn --arg c "$cmd" '$c')" \
      | bash "$HOOK" >/dev/null 2>&1
    printf '%-70s exit=%s\n' "$cmd" "$?"
done

# Should ALLOW (exit 0).
for cmd in \
  'CLOGLOG_ALLOW_DIRECT_API=1 curl http://127.0.0.1:8001/api/v1/tasks' \
  'curl http://127.0.0.1:8001/health' \
  'curl https://api.github.com/repos/sachinkundu/cloglog' ; do
    printf '{"tool":"Bash","input":{"command":%s}}' "$(jq -Rn --arg c "$cmd" '$c')" \
      | bash "$HOOK" >/dev/null 2>&1
    printf '%-70s exit=%s\n' "$cmd" "$?"
done
```

Expected: first loop all print `exit=2`; second loop all print `exit=0`.

For the full 14-case grid run `uvx showboat verify docs/demos/wt-b2-hooks/demo.md`.

---

### T-242 — `shutdown-artifacts/` reset on worktree bootstrap

**What changed.** `shutdown-artifacts/{work-log.md,learnings.md}` was
accidentally committed on 2026-04-05, so every worktree created after that
date inherited stale files from whichever agent last authored them. The fix
has two parts:

1. `shutdown-artifacts/` is now listed in `.gitignore` (root), and the stale
   files were removed from tracking.
2. `.cloglog/on-worktree-create.sh` `rm -rf`s the directory and re-creates it
   empty as part of bootstrap — so even if someone re-checks-in the files, a
   fresh worktree sees a clean slate.

**Manual checks.**

```bash
# shutdown-artifacts/ is gitignored and untracked.
git check-ignore -v shutdown-artifacts/work-log.md shutdown-artifacts/learnings.md
# Expected: each line starts with the .gitignore rule that matched.

# Bootstrap script has the reset block.
grep -nA2 'shutdown-artifacts' .cloglog/on-worktree-create.sh
# Expected: lines showing `rm -rf …/shutdown-artifacts` and a subsequent mkdir.
```

**Fresh-worktree simulation.**

```bash
# Mock a worktree directory with stale files and run the reset block in isolation.
TMPWT=$(mktemp -d) && mkdir -p "$TMPWT/shutdown-artifacts" \
  && echo "stale work log" > "$TMPWT/shutdown-artifacts/work-log.md" \
  && echo "stale learnings" > "$TMPWT/shutdown-artifacts/learnings.md"

ls "$TMPWT/shutdown-artifacts"     # before: two stale files

# Apply the reset the bootstrap applies.
rm -rf "$TMPWT/shutdown-artifacts" && mkdir -p "$TMPWT/shutdown-artifacts"

ls "$TMPWT/shutdown-artifacts"     # after: empty
rm -rf "$TMPWT"
```

Expected: two stale files → empty dir. Next real worktree created via
`git worktree add` will pick up exactly this path.

---

## Re-verify everything at once

```bash
# 1. Byte-exact demo replay for all three Wave-B deliveries.
uvx showboat verify docs/demos/wt-t215-shutdown-path/demo.md
uvx showboat verify docs/demos/wt-t214-apikey/demo.md
uvx showboat verify docs/demos/wt-b2-hooks/demo.md

# 2. Full quality gate (lint + types + 613 tests + contract + demo verify + mcp tests).
make quality
```

Expected: three `showboat: verified ✓` and one `Quality gate: PASSED` block
with **613 passed, 1 xfailed, 90.76 % coverage**.

---

## Not yet shipped

F-48 still owes three waves of work before it closes:

- **Wave C** — T-216 + T-243 (sync plugin docs to the new inbox path + bake
  the `agent_unregistered` event into the canonical protocol); T-244
  (post-merge mcp-server dist rebuild + `mcp_tools_updated` broadcast).
- **Wave D** — T-218 + T-221 (`request_shutdown` MCP tool + admin
  `force_unregister`); T-246 (auto-created close-off task per worktree).
- **Wave E** — T-220 (rewrite `/cloglog reconcile` and `/cloglog close-wave`
  around the cooperative-shutdown flow now that its primitives exist).

Plus T-213 (broaden "Stop on MCP failure" to cover runtime tool errors),
which has no encoded wave dependency but conceptually belongs near Wave C.

Current wave plan: `docs/superpowers/plans/2026-04-19-f48-execution-plan.md`.
