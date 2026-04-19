# T-247 — committed MCP config uses 127.0.0.1 so new worktrees work without a manual patch.

*2026-04-19T11:18:26Z by Showboat 0.6.1*
<!-- showboat-id: 2d6c5f0b-2be2-4556-9f7c-63c4732345b6 -->

Root cause: the committed `.mcp.json` pointed the MCP server at `http://localhost:8001`, but our HTTP server binds IPv4 only (`0.0.0.0`, not `[::]`). On hosts where `/etc/hosts` resolves `localhost` to `::1`, Node's fetch attempts IPv6 first (Happy Eyeballs) and fails with ECONNREFUSED. Every new worktree required a manual 127.0.0.1 patch. Fix: commit `127.0.0.1` as the default in three files.

Evidence 1 — `/etc/hosts` on Linux defines `::1` as an IPv6 loopback name. On dual-stack hosts where glibc returns AAAA for plain `localhost` first, Node's fetch attempts `[::1]` before `127.0.0.1`:

```bash
grep -E 'localhost|ip6-' /etc/hosts
```

```output
127.0.0.1 localhost
::1     ip6-localhost ip6-loopback
fe00::0 ip6-localnet
ff00::0 ip6-mcastprefix
ff02::1 ip6-allnodes
ff02::2 ip6-allrouters
```

Evidence 2 — self-contained reproduction: bind an HTTP server to 127.0.0.1 (just like gunicorn binds `0.0.0.0`, IPv4 only), then attempt both fetch variants. IPv6 fails with ECONNREFUSED; IPv4 succeeds. This is exactly what the MCP server saw with the old `localhost` default on hosts preferring AAAA:

```bash
node -e "const http=require('http');const srv=http.createServer((q,s)=>s.end('ok')).listen(0,'127.0.0.1',async()=>{const port=srv.address().port;try{const r=await fetch('http://[::1]:'+port+'/');console.log('IPv6 status',r.status);}catch(e){console.log('IPv6 fetch ERROR:',e.cause?.code||e.code||e.message);}try{const r=await fetch('http://127.0.0.1:'+port+'/');console.log('IPv4 status',r.status);}catch(e){console.log('IPv4 fetch ERROR:',e.cause?.code||e.code||e.message);}srv.close();});"
```

```output
IPv6 fetch ERROR: ECONNREFUSED
IPv4 status 200
```

Fix — three committed files switch the default from `localhost` to `127.0.0.1`. After this PR merges, every newly created worktree's MCP tools connect on first call with zero patching:

```bash
git diff origin/main -- .mcp.json .cloglog/config.yaml mcp-server/src/index.ts
```

```output
diff --git a/.cloglog/config.yaml b/.cloglog/config.yaml
index 29fc798..daf2848 100644
--- a/.cloglog/config.yaml
+++ b/.cloglog/config.yaml
@@ -1,6 +1,6 @@
 project: cloglog
 project_id: 4d9e825a-c911-4110-bcd5-9072d1887813
-backend_url: http://localhost:8001
+backend_url: http://127.0.0.1:8001
 prod_worktree_path: ../cloglog-prod
 quality_command: make quality
 
diff --git a/.mcp.json b/.mcp.json
index b7604c0..e895c83 100644
--- a/.mcp.json
+++ b/.mcp.json
@@ -4,7 +4,7 @@
       "command": "node",
       "args": ["/home/sachin/code/cloglog/mcp-server/dist/index.js"],
       "env": {
-        "CLOGLOG_URL": "http://localhost:8001",
+        "CLOGLOG_URL": "http://127.0.0.1:8001",
         "CLOGLOG_API_KEY": "56293e0a5a9848f88a2b1eab3cf43a8513d5bdab3209bb540dbfa10cd39f612d"
       }
     }
diff --git a/mcp-server/src/index.ts b/mcp-server/src/index.ts
index 1cce9cd..b96c3d0 100644
--- a/mcp-server/src/index.ts
+++ b/mcp-server/src/index.ts
@@ -9,7 +9,7 @@ import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
 import { CloglogClient } from './client.js'
 import { createServer } from './server.js'
 
-const CLOGLOG_URL = process.env.CLOGLOG_URL ?? 'http://localhost:8001'
+const CLOGLOG_URL = process.env.CLOGLOG_URL ?? 'http://127.0.0.1:8001'
 const CLOGLOG_API_KEY = process.env.CLOGLOG_API_KEY ?? ''
 const MCP_SERVICE_KEY = process.env.MCP_SERVICE_KEY ?? 'cloglog-mcp-dev'
 
```

Verify the committed state on main-after-merge (this block re-runs from any checkout and shows the three files now default to 127.0.0.1):

```bash
grep -HnE '127\.0\.0\.1|localhost' .mcp.json .cloglog/config.yaml mcp-server/src/index.ts | grep -vE '^#' || true
```

```output
.mcp.json:7:        "CLOGLOG_URL": "http://127.0.0.1:8001",
.cloglog/config.yaml:3:backend_url: http://127.0.0.1:8001
mcp-server/src/index.ts:12:const CLOGLOG_URL = process.env.CLOGLOG_URL ?? 'http://127.0.0.1:8001'
```
