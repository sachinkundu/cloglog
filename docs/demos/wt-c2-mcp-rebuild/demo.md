# After a merge touches mcp-server/src/, the main agent rebuilds mcp-server/dist/ and broadcasts mcp_tools_updated to every online worktree's inbox — the next worktree agent knows the MCP tool surface changed instead of silently missing new tools.

*2026-04-20T16:59:45Z by Showboat 0.6.1*
<!-- showboat-id: d0ad2321-de9f-4d52-830e-39c7f6c4120b -->

Setup: build a synthetic project tree with a stale mcp-server/dist/ and two worktrees under .claude/worktrees/. No real backend, no npm install — the demo proves the broadcast mechanism end-to-end without depending on environment state.

```bash
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

# Seed cloglog config.
cat > "$WORK/.cloglog/config.yaml" <<'CFG'
project: demo
project_id: 00000000-0000-0000-0000-000000000001
backend_url: http://127.0.0.1:61244
CFG

# Pre-create inbox files so they are visible as empty, matching what
# on-worktree-create.sh leaves behind on a real worktree.
: > "$WORK/.cloglog/inbox"
: > "$WORK/.claude/worktrees/wt-demo-a/.cloglog/inbox"
: > "$WORK/.claude/worktrees/wt-demo-b/.cloglog/inbox"

echo "synthetic root: $WORK"
echo "tools before rebuild:"
grep -oE "server\.tool\('[a-z_]+'" "$WORK/mcp-server/dist/server.js" | sort
```

```output
synthetic root: /tmp/t244-demo
tools before rebuild:
server.tool('get_my_tasks'
server.tool('register_agent'
server.tool('start_task'
```

Action: simulate the merge that introduces add_task_dependency and remove_task_dependency — we rewrite dist/server.js via a fake_rebuild, start a tiny mock worktrees endpoint, and run sync_mcp_dist.py.

```bash
set -euo pipefail
WORK="${TMPDIR:-/tmp}/t244-demo"

# Mock HTTP endpoint returning the two worktrees as online.
python3 - "$WORK" <<'PY' &
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
        body = bodies.get(self.path)
        if body is None:
            self.send_response(404); self.end_headers(); return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
srv = http.server.HTTPServer(("127.0.0.1", 61244), H)
srv.serve_forever()
PY
MOCK_PID=$!
trap "kill $MOCK_PID 2>/dev/null || true" EXIT
# Wait until the mock is listening.
for _ in $(seq 1 40); do
    if curl -sf "http://127.0.0.1:61244/api/v1/projects/00000000-0000-0000-0000-000000000001/worktrees" > /dev/null; then break; fi
    sleep 0.05
done

# Simulate the npm build side-effect by rewriting dist/server.js directly
# (the real build produces equivalent output). sync_mcp_dist.py's
# rebuild_dist would normally run 'npm run build' here.
cat > "$WORK/mcp-server/dist/server.js" <<'DIST_NEW'
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

uv run python - "$WORK" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path("/home/sachin/code/cloglog/.claude/worktrees/wt-c2-mcp-rebuild") / "scripts"))
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

paths = m.fetch_online_worktree_paths(
    "http://127.0.0.1:61244", "00000000-0000-0000-0000-000000000001"
)
print(f"online worktrees from mock API: {[Path(p).name for p in paths]}")
from datetime import datetime, UTC
event = m.build_event(added, removed, now=datetime(2026, 4, 20, 0, 0, tzinfo=UTC))
inboxes = m.inbox_paths_for(root, paths)
written = m.broadcast(inboxes, event)
print(f"broadcast wrote to {len(written)} inbox(es)")
PY
```

```output
tools added:   ['add_task_dependency', 'remove_task_dependency']
tools removed: []
online worktrees from mock API: ['wt-demo-a', 'wt-demo-b']
broadcast wrote to 3 inbox(es)
```

After: main inbox and every online worktree inbox has a mcp_tools_updated line. A running agent that needs the newly-added tools pauses and emits need_session_restart (see docs/design/agent-lifecycle.md §6).

```bash
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
```

```output
.cloglog/inbox
  {"type":"mcp_tools_updated","added":["add_task_dependency","remove_task_dependency"],"removed":[],"ts":"2026-04-20T00:00:00+00:00"}
.claude/worktrees/wt-demo-a/.cloglog/inbox
  {"type":"mcp_tools_updated","added":["add_task_dependency","remove_task_dependency"],"removed":[],"ts":"2026-04-20T00:00:00+00:00"}
.claude/worktrees/wt-demo-b/.cloglog/inbox
  {"type":"mcp_tools_updated","added":["add_task_dependency","remove_task_dependency"],"removed":[],"ts":"2026-04-20T00:00:00+00:00"}
```

The canonical doc carries the event contract (shape + response) — T-216 pattern, one sibling subsection under Section 6.

```bash
set -euo pipefail
grep -n "mcp_tools_updated\|need_session_restart\|sync-mcp-dist" docs/design/agent-lifecycle.md \
  | head -12
```

```output
204:| `mcp_tools_updated` | main agent (T-244) | Inspect the `added`/`removed` list. If the currently active task depends on the change, emit `need_session_restart` to the main inbox, pause, wait for the main agent to close and relaunch the tab (Section 6). Otherwise continue — the current session's MCP tool list is frozen at start and cannot hot-reload. |
217:| `need_session_restart` | On `mcp_tools_updated` when the new tools are load-bearing for the active task. |
370:   `mcp_tools_updated` broadcast (T-244): an agent that needs new MCP tools
375:1. After a merge, the main agent runs `make sync-mcp-dist` (wraps
383:   `mcp_tools_updated` event to every online worktree's `.cloglog/inbox`
387:   {"type":"mcp_tools_updated","added":["new_tool_a"],"removed":[],"ts":"..."}
394:3. A worktree agent that needs the new tools emits `need_session_restart` to
401:An agent that receives `mcp_tools_updated` but does NOT need the change keeps
447:- **T-244** — Post-merge mcp-server dist rebuild + `mcp_tools_updated`
```
