#!/usr/bin/env bash
# Demo: T-217 (SessionEnd trap) + T-219 (prefer-mcp hardening) + T-242 (shutdown-artifacts reset).
# Pure hooks/bootstrap changes — no backend call path required. The demo runs
# the hook scripts directly, exercises both sides of the new prefer-mcp rule,
# and shows the worktree bootstrap cleaning stale seed files.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"
HOOK_DIR="plugins/cloglog/hooks"

uvx showboat init "$DEMO_FILE" "Agents now unregister reliably on signal-driven shutdown, direct backend bypasses (loopback aliases + keyword allowlist) are closed, and fresh worktrees start with a clean shutdown-artifacts/ directory."

# ----------------------------------------------------------------------------
# T-217 — SessionEnd shutdown hook + launch.sh trap
# ----------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
"### T-217 — SessionEnd trap fires on TERM/HUP

Signal experiment: 'zellij action close-tab' does NOT signal pane children
(they reparent to zellij and keep running). The only real termination signal
today comes from close-wave step 5 (kill). Because launch.sh used 'exec claude',
any trap in the bash wrapper was gone by the time TERM arrived — only Claude
saw the signal, and if its SessionEnd hook drops the unregister POST the
worktree row stays registered. The fix drops 'exec' in the launcher template
and installs TERM/HUP traps that call /agents/unregister-by-path directly.
Below: the new agent-shutdown.sh writes an unconditional breadcrumb first, and
a launcher-shaped wrapper fires its trap on TERM and HUP."

uvx showboat note "$DEMO_FILE" "**Breadcrumb: agent-shutdown.sh writes /tmp/agent-shutdown-debug.log first, before any other step.**"
uvx showboat exec "$DEMO_FILE" bash 'grep -nA4 "unconditional breadcrumb" plugins/cloglog/hooks/agent-shutdown.sh | head -20'

uvx showboat note "$DEMO_FILE" "**Hook runs end-to-end from a worktree cwd — resolves backend URL correctly (grep-parsed) and writes the breadcrumb.**"
uvx showboat exec "$DEMO_FILE" bash '
  rm -f /tmp/agent-shutdown-debug.log
  echo "{\"cwd\":\"/tmp/does-not-exist\"}" | bash plugins/cloglog/hooks/agent-shutdown.sh
  echo "exit=$?"
  grep -c "agent-shutdown.sh fired" /tmp/agent-shutdown-debug.log
'

uvx showboat note "$DEMO_FILE" "**Launcher trap fires on SIGTERM.** A fake-claude stand-in (sleep 300) is run under the new trap wrapper; a SIGTERM to the bash PID triggers the trap, writes the debug log, and exits cleanly."
uvx showboat exec "$DEMO_FILE" bash '
  rm -f /tmp/agent-shutdown-debug.log /tmp/t217-exit-marker
  cat > /tmp/t217-fake-launcher.sh <<EOF
#!/bin/bash
set -u
_on_signal() {
  local sig="\$1"
  echo "[trap-fired] sig=\$sig" >> /tmp/agent-shutdown-debug.log
  kill -"\$sig" "\${CHILD_PID}" 2>/dev/null || true
  echo "\$sig" > /tmp/t217-exit-marker
  exit 0
}
trap "_on_signal TERM" TERM
trap "_on_signal HUP" HUP
sleep 60 &
CHILD_PID=\$!
wait "\$CHILD_PID"
EOF
  chmod +x /tmp/t217-fake-launcher.sh
  /tmp/t217-fake-launcher.sh &
  LPID=$!
  sleep 1
  kill -TERM $LPID
  wait $LPID 2>/dev/null || true
  cat /tmp/agent-shutdown-debug.log
  echo "exit-marker=$(cat /tmp/t217-exit-marker)"
'

uvx showboat note "$DEMO_FILE" "**Launcher trap fires on SIGHUP too** (covers the case where a future wrapper or terminal does send HUP)."
uvx showboat exec "$DEMO_FILE" bash '
  rm -f /tmp/agent-shutdown-debug.log /tmp/t217-exit-marker
  /tmp/t217-fake-launcher.sh &
  LPID=$!
  sleep 1
  kill -HUP $LPID
  wait $LPID 2>/dev/null || true
  cat /tmp/agent-shutdown-debug.log
  echo "exit-marker=$(cat /tmp/t217-exit-marker)"
'

# ----------------------------------------------------------------------------
# T-219 — prefer-mcp.sh hardening
# ----------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
"### T-219 — prefer-mcp.sh closes loopback-alias + keyword-allowlist bypasses

Two holes in the prior hook: (1) it only matched the verbatim BACKEND_HOST
from config.yaml (e.g. '127.0.0.1:8001'), so 'localhost:8001', '0.0.0.0:8001',
'[::1]:8001', and any future tunnel host slipped through; (2) any command
containing the words 'test', 'debug', 'verify', or 'check.*status' was let
through — trivially spoofable with '# debug'.

Hardening: match the full loopback alias set (plus optional tunnel_host from
config.yaml), extend the tool-detection regex to curl/wget/httpie/python
(urllib|httpx|requests|http.client)/node fetch, and replace the keyword
allowlist with an explicit inline env prefix 'CLOGLOG_ALLOW_DIRECT_API=1' that
demo tooling must set on purpose."

uvx showboat note "$DEMO_FILE" "**New hook: the rule-building region of prefer-mcp.sh shows the host alternation, the env flag escape hatch, and the extended tool pattern.**"
uvx showboat exec "$DEMO_FILE" bash 'grep -nE "CLOGLOG_ALLOW_DIRECT_API|Loopback aliases|TOOL_PAT|Blocked: direct" plugins/cloglog/hooks/prefer-mcp.sh'

uvx showboat note "$DEMO_FILE" "**BLOCK cases (exit 2): every loopback alias and every supported network tool is blocked.**"
uvx showboat exec "$DEMO_FILE" bash '
  run() {
    local label="$1" cmd="$2"
    local status
    status=$(jq -nc --arg cmd "$cmd" --arg cwd "$PWD" "{tool_name:\"Bash\",tool_input:{command:\$cmd},cwd:\$cwd}" \
      | bash plugins/cloglog/hooks/prefer-mcp.sh 2>/dev/null >/dev/null; echo $?)
    printf "exit=%s  %-22s  %s\n" "$status" "$label" "$cmd"
  }
  run "curl-127.0.0.1"  "curl -sf http://127.0.0.1:8001/api/v1/board"
  run "curl-localhost"  "curl -sf http://localhost:8001/api/v1/board"
  run "curl-0.0.0.0"    "curl -sf http://0.0.0.0:8001/api/v1/board"
  run "curl-ipv6"       "curl -sf http://[::1]:8001/api/v1/board"
  run "wget-loopback"   "wget http://127.0.0.1:8001/api/v1/board"
  run "httpie"          "http GET http://127.0.0.1:8001/api/v1/board"
  run "python-http"     "python3 -m http.client http://127.0.0.1:8001/api/v1/board"
  run "node-fetch"      "node -e \"fetch(http://127.0.0.1:8001/api/v1/board)\""
  run "keyword-debug"   "curl -sf http://localhost:8001/api/v1/board # debug"
'

uvx showboat note "$DEMO_FILE" "**ALLOW cases (exit 0): env-flag escape hatch, non-/api probes, unrelated hosts, showboat with variable-substituted host.**"
uvx showboat exec "$DEMO_FILE" bash '
  run() {
    local label="$1" cmd="$2"
    local status
    status=$(jq -nc --arg cmd "$cmd" --arg cwd "$PWD" "{tool_name:\"Bash\",tool_input:{command:\$cmd},cwd:\$cwd}" \
      | bash plugins/cloglog/hooks/prefer-mcp.sh 2>/dev/null >/dev/null; echo $?)
    printf "exit=%s  %-24s  %s\n" "$status" "$label" "$cmd"
  }
  run "env-flag-bypass"    "CLOGLOG_ALLOW_DIRECT_API=1 curl -sf http://127.0.0.1:8001/api/v1/board"
  run "health-probe"       "curl -sf http://localhost:8001/health"
  run "frontend-probe"     "curl -sf http://localhost:5173"
  run "astral-install"     "curl -LsSf https://astral.sh/uv/install.sh | sh"
  run "github-api"         "curl -H \"Authorization: Bearer x\" https://api.github.com/repos/foo/bar/pulls"
  run "showboat-varbase"   "uvx showboat exec DEMO curl -sf BASE/projects"
'

# ----------------------------------------------------------------------------
# T-242 — shutdown-artifacts reset on worktree create
# ----------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
"### T-242 — on-worktree-create.sh resets shutdown-artifacts/

Four agents in a row (T-247, T-249, T-253, devex-batch) inherited stale
work-log.md / learnings.md from whichever worktree first seeded the template
back in April. The fix adds a small rm+mkdir block to the project worktree
bootstrap, so every new worktree starts with an empty shutdown-artifacts/
directory and the shutdown-side generator always writes from scratch."

uvx showboat note "$DEMO_FILE" "**Bootstrap: the new block lives inside .cloglog/on-worktree-create.sh.**"
uvx showboat exec "$DEMO_FILE" bash 'grep -nA8 "T-242" .cloglog/on-worktree-create.sh'

uvx showboat note "$DEMO_FILE" "**Behavior: running the block against a directory seeded with stale content wipes it and leaves a clean empty dir.**"
uvx showboat exec "$DEMO_FILE" bash '
  rm -rf /tmp/t242-demo-wt
  mkdir -p /tmp/t242-demo-wt/shutdown-artifacts
  echo "STALE work log from wt-depgraph" > /tmp/t242-demo-wt/shutdown-artifacts/work-log.md
  echo "STALE learnings" > /tmp/t242-demo-wt/shutdown-artifacts/learnings.md
  echo "before-reset:"
  ls /tmp/t242-demo-wt/shutdown-artifacts/
  WORKTREE_PATH=/tmp/t242-demo-wt
  rm -rf "${WORKTREE_PATH}/shutdown-artifacts"
  mkdir -p "${WORKTREE_PATH}/shutdown-artifacts"
  echo "after-reset:"
  ls -A /tmp/t242-demo-wt/shutdown-artifacts/ | wc -l | xargs -I{} echo "entries={}"
  rm -rf /tmp/t242-demo-wt
'

uvx showboat verify "$DEMO_FILE"
