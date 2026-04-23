# docs/demos/wt-c2-mcp-rebuild/demo-script.sh now binds its mock HTTP server to an OS-assigned ephemeral port (port 0) — no more hardcoded :61244 that could collide with any other process on the host or with a second make demo run (T-256).

*2026-04-23T04:35:04Z by Showboat 0.6.1*
<!-- showboat-id: eef49408-a66c-4b96-aa56-94b4bfd98e00 -->

Before: docs/demos/wt-c2-mcp-rebuild/demo-script.sh called http.server.HTTPServer((127.0.0.1, 61244), H). Two concurrent make-demo runs on the same host would race for the same port; the second would crash with EADDRINUSE and showboat verify would fail non-deterministically. Codex flagged this during PR #172 round 2 review.

After: bind to port 0, let the kernel pick a free port, write it to a mock-port file, then have the shell poll the file and substitute the port into subsequent URLs. The ephemeral port is intentionally NOT echoed to the demo output so showboat verify remains byte-exact.

Proof 1 — the script source. Hardcoded port :61244 is gone; the bind is now to port 0 and the mock-port handshake is in place.

```bash

set -euo pipefail
if grep -q "127.0.0.1.*61244\|61244.*127.0.0.1" docs/demos/wt-c2-mcp-rebuild/demo-script.sh; then
  echo "FAIL: 61244 still appears in demo-script.sh"
  exit 1
fi
if grep -q "HTTPServer((\"127.0.0.1\", 0)" docs/demos/wt-c2-mcp-rebuild/demo-script.sh; then
  echo "OK: demo-script.sh binds to port 0"
else
  echo "FAIL: expected port-0 bind not found"
  exit 1
fi
if grep -q "mock-port" docs/demos/wt-c2-mcp-rebuild/demo-script.sh; then
  echo "OK: mock-port handshake present"
else
  echo "FAIL: mock-port handshake missing"
  exit 1
fi

```

```output
OK: demo-script.sh binds to port 0
OK: mock-port handshake present
```

Proof 2 — the captured demo output. showboats verify step re-executes every exec block in docs/demos/wt-c2-mcp-rebuild/demo.md byte-exactly; the regenerated demo.md carries no reference to :61244.

```bash

set -euo pipefail
if grep -q "61244" docs/demos/wt-c2-mcp-rebuild/demo.md; then
  echo "FAIL: 61244 still appears in the captured demo.md"
  exit 1
else
  echo "OK: no 61244 reference in docs/demos/wt-c2-mcp-rebuild/demo.md"
fi

```

```output
OK: no 61244 reference in docs/demos/wt-c2-mcp-rebuild/demo.md
```

Proof 3 — showboat verify on the patched c2 demo passes. We run verify in a subshell and capture only the exit code (verify output contains timestamps, which would break byte-exact re-verification of THIS demo).

```bash

set -euo pipefail
if uvx showboat verify docs/demos/wt-c2-mcp-rebuild/demo.md >/dev/null 2>&1; then
  echo "OK: uvx showboat verify docs/demos/wt-c2-mcp-rebuild/demo.md exit=0"
else
  echo "FAIL: showboat verify on patched c2 demo returned non-zero"
  exit 1
fi

```

```output
OK: uvx showboat verify docs/demos/wt-c2-mcp-rebuild/demo.md exit=0
```
