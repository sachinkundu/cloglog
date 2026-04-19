#!/usr/bin/env bash
# Demo: T-247 — committed MCP config uses 127.0.0.1 so new worktrees work without a manual patch.
# Blocks are self-contained so `showboat verify` runs anywhere (no backend required).
set -euo pipefail

DEMO_FILE="docs/demos/$(git rev-parse --abbrev-ref HEAD)/demo.md"

uvx showboat init "$DEMO_FILE" "T-247 — committed MCP config uses 127.0.0.1 so new worktrees work without a manual patch."

uvx showboat note "$DEMO_FILE" "Root cause: the committed \`.mcp.json\` pointed the MCP server at \`http://localhost:8001\`, but our HTTP server binds IPv4 only (\`0.0.0.0\`, not \`[::]\`). On hosts where \`/etc/hosts\` resolves \`localhost\` to \`::1\`, Node's fetch attempts IPv6 first (Happy Eyeballs) and fails with ECONNREFUSED. Every new worktree required a manual 127.0.0.1 patch. Fix: commit \`127.0.0.1\` as the default in three files."

uvx showboat note "$DEMO_FILE" "Evidence 1 — \`/etc/hosts\` on Linux defines \`::1\` as an IPv6 loopback name. On dual-stack hosts where glibc returns AAAA for plain \`localhost\` first, Node's fetch attempts \`[::1]\` before \`127.0.0.1\`:"
uvx showboat exec "$DEMO_FILE" bash "grep -E 'localhost|ip6-' /etc/hosts"

uvx showboat note "$DEMO_FILE" "Evidence 2 — self-contained reproduction: bind an HTTP server to 127.0.0.1 (just like gunicorn binds \`0.0.0.0\`, IPv4 only), then attempt both fetch variants. IPv6 fails with ECONNREFUSED; IPv4 succeeds. This is exactly what the MCP server saw with the old \`localhost\` default on hosts preferring AAAA:"
uvx showboat exec "$DEMO_FILE" bash "node -e \"const http=require('http');const srv=http.createServer((q,s)=>s.end('ok')).listen(0,'127.0.0.1',async()=>{const port=srv.address().port;try{const r=await fetch('http://[::1]:'+port+'/');console.log('IPv6 status',r.status);}catch(e){console.log('IPv6 fetch ERROR:',e.cause?.code||e.code||e.message);}try{const r=await fetch('http://127.0.0.1:'+port+'/');console.log('IPv4 status',r.status);}catch(e){console.log('IPv4 fetch ERROR:',e.cause?.code||e.code||e.message);}srv.close();});\""

uvx showboat note "$DEMO_FILE" "Fix — three committed files switch the default from \`localhost\` to \`127.0.0.1\`. After this PR merges, every newly created worktree's MCP tools connect on first call with zero patching:"
uvx showboat exec "$DEMO_FILE" bash "git diff origin/main -- .mcp.json .cloglog/config.yaml mcp-server/src/index.ts"

uvx showboat note "$DEMO_FILE" "Verify the committed state on main-after-merge (this block re-runs from any checkout and shows the three files now default to 127.0.0.1):"
uvx showboat exec "$DEMO_FILE" bash "grep -HnE '127\\.0\\.0\\.1|localhost' .mcp.json .cloglog/config.yaml mcp-server/src/index.ts | grep -vE '^#' || true"

uvx showboat verify "$DEMO_FILE"
