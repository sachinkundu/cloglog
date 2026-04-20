# Agents now unregister reliably on signal-driven shutdown, direct backend bypasses (loopback aliases + keyword allowlist) are closed, and fresh worktrees start with a clean shutdown-artifacts/ directory.

*2026-04-20T11:20:02Z by Showboat 0.6.1*
<!-- showboat-id: 2d8f263c-bc1d-4dd6-8fdd-ee2155f07e93 -->

### T-217 — SessionEnd trap fires on TERM/HUP

Signal experiment: 'zellij action close-tab' does NOT signal pane children
(they reparent to zellij and keep running). The only real termination signal
today comes from close-wave step 5 (kill). Because launch.sh used 'exec claude',
any trap in the bash wrapper was gone by the time TERM arrived — only Claude
saw the signal, and if its SessionEnd hook drops the unregister POST the
worktree row stays registered. The fix drops 'exec' in the launcher template
and installs TERM/HUP traps that call /agents/unregister-by-path directly.
Below: the new agent-shutdown.sh writes an unconditional breadcrumb first, and
a launcher-shaped wrapper fires its trap on TERM and HUP.

**Breadcrumb: agent-shutdown.sh writes /tmp/agent-shutdown-debug.log first, before any other step.**

```bash
grep -nA4 "unconditional breadcrumb" plugins/cloglog/hooks/agent-shutdown.sh | head -20
```

```output
9:# T-217: write an unconditional breadcrumb as the very first step so that
10-# post-incident investigators can tell whether Claude ran SessionEnd at all,
11-# even if a subsequent step errors out. Presence of this file answers the
12-# "did the hook fire?" question; absence means Claude never ran it.
13-{
```

**Hook runs end-to-end from a worktree cwd — resolves backend URL correctly (grep-parsed) and writes the breadcrumb.**

```bash

  rm -f /tmp/agent-shutdown-debug.log
  echo "{\"cwd\":\"/tmp/does-not-exist\"}" | bash plugins/cloglog/hooks/agent-shutdown.sh
  echo "exit=$?"
  grep -c "agent-shutdown.sh fired" /tmp/agent-shutdown-debug.log

```

```output
plugins/cloglog/hooks/agent-shutdown.sh: line 20: cd: /tmp/does-not-exist: No such file or directory
exit=0
1
```

**Launcher trap fires on SIGTERM.** A fake-claude stand-in (sleep 300) is run under the new trap wrapper; a SIGTERM to the bash PID triggers the trap, writes the debug log, and exits cleanly.

```bash

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

```

```output
[trap-fired] sig=TERM
exit-marker=TERM
```

**Launcher trap fires on SIGHUP too** (covers the case where a future wrapper or terminal does send HUP).

```bash

  rm -f /tmp/agent-shutdown-debug.log /tmp/t217-exit-marker
  /tmp/t217-fake-launcher.sh &
  LPID=$!
  sleep 1
  kill -HUP $LPID
  wait $LPID 2>/dev/null || true
  cat /tmp/agent-shutdown-debug.log
  echo "exit-marker=$(cat /tmp/t217-exit-marker)"

```

```output
[trap-fired] sig=HUP
exit-marker=HUP
```

### T-219 — prefer-mcp.sh closes loopback-alias + keyword-allowlist bypasses

Two holes in the prior hook: (1) it only matched the verbatim BACKEND_HOST
from config.yaml (e.g. '127.0.0.1:8001'), so 'localhost:8001', '0.0.0.0:8001',
'[::1]:8001', and any future tunnel host slipped through; (2) any command
containing the words 'test', 'debug', 'verify', or 'check.*status' was let
through — trivially spoofable with '# debug'.

Hardening: match the full loopback alias set (plus optional tunnel_host from
config.yaml), extend the tool-detection regex to curl/wget/httpie/python
(urllib|httpx|requests|http.client)/node fetch, and replace the keyword
allowlist with an explicit inline env prefix 'CLOGLOG_ALLOW_DIRECT_API=1' that
demo tooling must set on purpose.

**New hook: the rule-building region of prefer-mcp.sh shows the host alternation, the env flag escape hatch, and the extended tool pattern.**

```bash
grep -nE "CLOGLOG_ALLOW_DIRECT_API|Loopback aliases|TOOL_PAT|Blocked: direct" plugins/cloglog/hooks/prefer-mcp.sh
```

```output
13:#       prefix `CLOGLOG_ALLOW_DIRECT_API=1` that demo tooling must set
17:#       with `CLOGLOG_ALLOW_DIRECT_API=1 ...` inline.
32:# Inline env prefix only — `export CLOGLOG_ALLOW_DIRECT_API=1` from a prior
36:#   CLOGLOG_ALLOW_DIRECT_API=1 uvx showboat exec ... 'curl -sf "$BASE/..."'
37:if echo "$COMMAND_FLAT" | grep -qE '(^|[[:space:];&|(])CLOGLOG_ALLOW_DIRECT_API=1(\b|[[:space:]])'; then
88:# Loopback aliases that all resolve to the backend running on the dev host.
130:TOOL_PAT='(\<(curl|wget)\>'
131:TOOL_PAT+='|(^|[[:space:];&|(])http[[:space:]]+'
132:TOOL_PAT+='|python3?[[:space:]]+-m[[:space:]]+http\.client'
133:TOOL_PAT+='|python3?[[:space:]]+-c[[:space:]].*(urllib|httpx|requests)'
134:TOOL_PAT+='|node[[:space:]]+(-e|--eval)[[:space:]].*fetch\('
135:TOOL_PAT+=')'
143:if echo "$COMMAND_FLAT" | grep -qE "${TOOL_PAT}[^;&|]*?(${HOST_ALT})(:[0-9]+)?/api"; then
144:  echo "Blocked: direct cloglog backend access prohibited." >&2
147:  echo "  Legitimate demo-only escape hatch: inline 'CLOGLOG_ALLOW_DIRECT_API=1 ...'" >&2
```

**BLOCK cases (exit 2): every loopback alias and every supported network tool is blocked.**

```bash

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

```

```output
exit=2  curl-127.0.0.1          curl -sf http://127.0.0.1:8001/api/v1/board
exit=2  curl-localhost          curl -sf http://localhost:8001/api/v1/board
exit=2  curl-0.0.0.0            curl -sf http://0.0.0.0:8001/api/v1/board
exit=2  curl-ipv6               curl -sf http://[::1]:8001/api/v1/board
exit=2  wget-loopback           wget http://127.0.0.1:8001/api/v1/board
exit=2  httpie                  http GET http://127.0.0.1:8001/api/v1/board
exit=2  python-http             python3 -m http.client http://127.0.0.1:8001/api/v1/board
exit=2  node-fetch              node -e "fetch(http://127.0.0.1:8001/api/v1/board)"
exit=2  keyword-debug           curl -sf http://localhost:8001/api/v1/board # debug
```

**ALLOW cases (exit 0): env-flag escape hatch, non-/api probes, unrelated hosts, showboat with variable-substituted host.**

```bash

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

```

```output
exit=0  env-flag-bypass           CLOGLOG_ALLOW_DIRECT_API=1 curl -sf http://127.0.0.1:8001/api/v1/board
exit=0  health-probe              curl -sf http://localhost:8001/health
exit=0  frontend-probe            curl -sf http://localhost:5173
exit=0  astral-install            curl -LsSf https://astral.sh/uv/install.sh | sh
exit=0  github-api                curl -H "Authorization: Bearer x" https://api.github.com/repos/foo/bar/pulls
exit=0  showboat-varbase          uvx showboat exec DEMO curl -sf BASE/projects
```

### T-242 — on-worktree-create.sh resets shutdown-artifacts/

Four agents in a row (T-247, T-249, T-253, devex-batch) inherited stale
work-log.md / learnings.md from whichever worktree first seeded the template
back in April. The fix adds a small rm+mkdir block to the project worktree
bootstrap, so every new worktree starts with an empty shutdown-artifacts/
directory and the shutdown-side generator always writes from scratch.

**Bootstrap: the new block lives inside .cloglog/on-worktree-create.sh.**

```bash
grep -nA8 "T-242" .cloglog/on-worktree-create.sh
```

```output
11:# T-242: every worktree starts with a fresh shutdown-artifacts/ directory.
12-# Without this, newly created worktrees inherit stale work-log.md / learnings.md
13-# from whichever worktree seeded the template (originally wt-depgraph,
14-# 2026-04-05). Four downstream agents (T-247, T-249, T-253, devex-batch) had
15-# to overwrite before noticing the stale content. Agents generate these
16-# files from scratch during the shutdown sequence — no template seeding is
17-# required here; see docs/design/agent-lifecycle.md §2 step 4.
18-if [[ -n "${WORKTREE_PATH:-}" ]]; then
19-  rm -rf "${WORKTREE_PATH}/shutdown-artifacts"
```

**Behavior: running the block against a directory seeded with stale content wipes it and leaves a clean empty dir.**

```bash

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

```

```output
before-reset:
learnings.md
work-log.md
after-reset:
entries=0
```
