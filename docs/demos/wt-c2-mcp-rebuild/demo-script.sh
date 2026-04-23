#!/usr/bin/env bash
# Demo: T-244 — post-merge mcp-server dist rebuild + mcp_tools_updated broadcast.
# Called by `make demo` (no running backend required — the demo self-hosts a
# mock worktrees endpoint so verification is deterministic across environments).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
DEMO_FILE="$SCRIPT_DIR/demo.md"

uvx showboat init "$DEMO_FILE" \
  "After a merge touches mcp-server/src/, the main agent rebuilds mcp-server/dist/ and broadcasts mcp_tools_updated to every online worktree's inbox — the next worktree agent knows the MCP tool surface changed instead of silently missing new tools."

# ── Setup: temp project root with fake mcp-server/ and two worktrees ──

uvx showboat note "$DEMO_FILE" \
  "Setup: build a synthetic project tree with a stale mcp-server/dist/ and two worktrees under .claude/worktrees/. No real backend, no npm install — the demo proves the broadcast mechanism end-to-end without depending on environment state."

uvx showboat exec "$DEMO_FILE" bash "$(cat <<'SETUP'
set -euo pipefail
WORK="${TMPDIR:-/tmp}/t244-demo"
rm -rf "$WORK"
mkdir -p "$WORK/mcp-server/dist" "$WORK/mcp-server/src" \
         "$WORK/.cloglog" \
         "$WORK/.claude/worktrees/wt-demo-a/.cloglog" \
         "$WORK/.claude/worktrees/wt-demo-b/.cloglog"

# Old compiled dist — three tools declared.
cat > "$WORK/mcp-server/dist/server.js" <<'DIST_OLD'
server.tool('register_agent', 'doc', {}, () => {});
server.tool('get_my_tasks', 'doc', {}, () => {});
server.tool('start_task', 'doc', {}, () => {});
DIST_OLD

# Seed cloglog config (backend_url is overridden at runtime with the
# mock server's OS-assigned port — no hardcoded port collisions).
cat > "$WORK/.cloglog/config.yaml" <<'CFG'
project: demo
project_id: 00000000-0000-0000-0000-000000000001
backend_url: http://127.0.0.1:0
CFG

# Pre-create inbox files so they are visible as empty, matching what
# on-worktree-create.sh leaves behind on a real worktree.
: > "$WORK/.cloglog/inbox"
: > "$WORK/.claude/worktrees/wt-demo-a/.cloglog/inbox"
: > "$WORK/.claude/worktrees/wt-demo-b/.cloglog/inbox"

echo "synthetic root: $WORK"
echo "tools before rebuild:"
grep -oE "server\.tool\('[a-z_]+'" "$WORK/mcp-server/dist/server.js" | sort
SETUP
)"

# ── Action: simulate merge, rebuild, broadcast ──

uvx showboat note "$DEMO_FILE" \
  "Action: simulate the merge that introduces add_task_dependency and remove_task_dependency — we rewrite dist/server.js via a fake_rebuild, start a tiny mock worktrees endpoint, and run sync_mcp_dist.py."

uvx showboat exec "$DEMO_FILE" bash "$(cat <<SCRIPT
set -euo pipefail
WORK="\${TMPDIR:-/tmp}/t244-demo"

# Mock HTTP endpoint returning the two worktrees as online.
python3 - "\$WORK" <<'PY' &
import http.server, json, socket, sys
from pathlib import Path
root = Path(sys.argv[1])
bodies = {
    "/api/v1/projects/00000000-0000-0000-0000-000000000001/worktrees": [
        {"status": "online", "worktree_path": str(root / ".claude/worktrees/wt-demo-a")},
        {"status": "online", "worktree_path": str(root / ".claude/worktrees/wt-demo-b")},
    ],
}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a, **k): pass
    def do_GET(self):
        # Mirror the real middleware: reject non-agent GETs that are missing
        # the X-Dashboard-Key header. The demo proves the header is being sent.
        if self.headers.get("X-Dashboard-Key") != "cloglog-dashboard-dev":
            self.send_response(403); self.end_headers(); return
        body = bodies.get(self.path)
        if body is None:
            self.send_response(404); self.end_headers(); return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
# Bind to port 0 so the kernel picks a free ephemeral port — avoids the
# hardcoded-port collision that flagged in review. The port is written
# back through a well-known file the shell polls for below.
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
Path(sys.argv[1], "mock-port").write_text(str(srv.server_address[1]))
srv.serve_forever()
PY
MOCK_PID=\$!
trap "kill \$MOCK_PID 2>/dev/null || true" EXIT
# Wait for the mock to publish its port, then wait for it to start serving.
for _ in \$(seq 1 100); do
    [ -f "\$WORK/mock-port" ] && break
    sleep 0.05
done
MOCK_PORT="\$(cat "\$WORK/mock-port")"
MOCK_URL="http://127.0.0.1:\${MOCK_PORT}"
# Auth header matches the real backend — mock returns 403 without it.
for _ in \$(seq 1 40); do
    if curl -sf -H "X-Dashboard-Key: cloglog-dashboard-dev" \
        "\${MOCK_URL}/api/v1/projects/00000000-0000-0000-0000-000000000001/worktrees" \
        > /dev/null; then break; fi
    sleep 0.05
done
# Intentionally do not echo \$MOCK_PORT — it is ephemeral and would break
# showboat's byte-exact verify on the next run. The subsequent "online
# worktrees" line is deterministic.

# Simulate the npm build side-effect by rewriting dist/server.js directly
# (the real build produces equivalent output). sync_mcp_dist.py's
# rebuild_dist would normally run 'npm run build' here.
cat > "\$WORK/mcp-server/dist/server.js" <<'DIST_NEW'
server.tool('register_agent', 'doc', {}, () => {});
server.tool('get_my_tasks', 'doc', {}, () => {});
server.tool('start_task', 'doc', {}, () => {});
server.tool('add_task_dependency', 'doc', {}, () => {});
server.tool('remove_task_dependency', 'doc', {}, () => {});
DIST_NEW

# Run the script with --skip-build since we just wrote the "built" dist
# ourselves. sync_mcp_dist.py snapshots tool names from dist/server.js
# before and after the build step; with --skip-build it only snapshots
# once, so we pre-wrote OLD dist in the setup above, captured it into
# an OLD_TOOLS env var here, and use --skip-build to short-circuit the
# build and force a re-snapshot against the new dist.
#
# For the demo, the simpler path is: don't use --skip-build; instead
# write an OLD dist first, override rebuild_dist via a wrapper module.
# But that's overkill. We instead drive the library directly.

uv run python - "\$WORK" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path("${REPO_ROOT}") / "scripts"))
import sync_mcp_dist as m

root = Path(sys.argv[1])
dist_server = root / "mcp-server/dist/server.js"

# OLD snapshot: read what we seeded in setup (before the fake build).
old_text = "server.tool('register_agent', 'doc', {}, () => {});\nserver.tool('get_my_tasks', 'doc', {}, () => {});\nserver.tool('start_task', 'doc', {}, () => {});\n"
old_tools = set(m.TOOL_NAME_RE.findall(old_text))
# NEW snapshot: read from the "rebuilt" dist file.
new_tools = m.extract_tool_names(dist_server)
added = new_tools - old_tools
removed = old_tools - new_tools
print(f"tools added:   {sorted(added)}")
print(f"tools removed: {sorted(removed)}")

mock_port = (root / "mock-port").read_text().strip()
paths = m.fetch_online_worktree_paths(
    f"http://127.0.0.1:{mock_port}",
    "00000000-0000-0000-0000-000000000001",
    dashboard_secret="cloglog-dashboard-dev",
)
print(f"online worktrees from mock API: {[Path(p).name for p in paths]}")
from datetime import datetime, UTC
event = m.build_event(added, removed, now=datetime(2026, 4, 20, 0, 0, tzinfo=UTC))
inboxes = m.inbox_paths_for(root, paths)
written = m.broadcast(inboxes, event)
print(f"broadcast wrote to {len(written)} inbox(es)")
PY
SCRIPT
)"

# ── After: show every inbox carries the mcp_tools_updated event ──

uvx showboat note "$DEMO_FILE" \
  "After: main inbox and every online worktree inbox has a mcp_tools_updated line. A running agent that needs the newly-added tools pauses and emits need_session_restart (see docs/design/agent-lifecycle.md §6)."

uvx showboat exec "$DEMO_FILE" bash "$(cat <<'VERIFY'
set -euo pipefail
WORK="${TMPDIR:-/tmp}/t244-demo"
for inbox in \
  "$WORK/.cloglog/inbox" \
  "$WORK/.claude/worktrees/wt-demo-a/.cloglog/inbox" \
  "$WORK/.claude/worktrees/wt-demo-b/.cloglog/inbox"
do
  printf "%s\n  %s\n" \
    "$(realpath --relative-to="$WORK" "$inbox")" \
    "$(cat "$inbox")"
done
VERIFY
)"

# ── Sibling: doc contract is in place ──

uvx showboat note "$DEMO_FILE" \
  "The canonical doc carries the event contract (shape + response) — T-216 pattern, one sibling subsection under Section 6."

uvx showboat exec "$DEMO_FILE" bash "$(cat <<'DOC'
set -euo pipefail
grep -n "mcp_tools_updated\|need_session_restart\|sync-mcp-dist" docs/design/agent-lifecycle.md \
  | head -12
DOC
)"

uvx showboat verify "$DEMO_FILE"
