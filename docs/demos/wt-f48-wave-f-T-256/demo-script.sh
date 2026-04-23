#!/usr/bin/env bash
# Demo: T-256 — docs/demos/wt-c2-mcp-rebuild/demo-script.sh now binds its
# mock HTTP server to port 0 (OS-assigned ephemeral) instead of hardcoded
# :61244. Removes the port-collision foot-gun that flagged in codex review
# of PR #172 and lets two concurrent `make demo` runs on the same host
# coexist. The C2 agent produced the fix as `t244-demo-port-fix.patch`
# before PR #172 merged; this PR applies it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

# Self-locate so the committed path and the regenerated path always
# agree regardless of branch name (T-259 codex round 1 pattern).
DEMO_DIR="${SCRIPT_DIR#"$REPO_ROOT"/}"
DEMO_FILE="$DEMO_DIR/demo.md"

rm -f "$DEMO_FILE"

uvx showboat init "$DEMO_FILE" \
  "docs/demos/wt-c2-mcp-rebuild/demo-script.sh no longer binds its mock HTTP server to the hardcoded :61244 port flagged in PR #172 review — the kernel picks a free ephemeral port instead (T-256)."

uvx showboat note "$DEMO_FILE" \
  "Before: docs/demos/wt-c2-mcp-rebuild/demo-script.sh called http.server.HTTPServer((127.0.0.1, 61244), H). Any other process that happened to already own :61244 — or a sibling that bound it first — would cause the bind() to fail with EADDRINUSE and showboat verify would error non-deterministically. Codex flagged this during PR #172 round 2 review."

uvx showboat note "$DEMO_FILE" \
  "After: bind to port 0, let the kernel pick a free port, write it to a mock-port file, then have the shell poll the file and substitute the port into subsequent URLs. The ephemeral port is intentionally NOT echoed to the demo output so showboat verify remains byte-exact."

uvx showboat note "$DEMO_FILE" \
  "Scope note: this PR fixes the specific port-61244 hazard flagged in PR #172. The c2 demo still uses a shared WORK=/tmp/t244-demo root across runs (setup, mock-port handshake, inboxes all live there), so two strictly concurrent make-demo invocations on the same host could still clobber each other at the filesystem level. That is a separate co-residual concern that T-256 does NOT close — see codex round 2 note on this PR."

uvx showboat note "$DEMO_FILE" \
  "Proof 1 — the script source. Hardcoded port :61244 is gone; the bind is now to port 0 and the mock-port handshake is in place."

uvx showboat exec "$DEMO_FILE" bash '
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
'

uvx showboat note "$DEMO_FILE" \
  "Proof 2 — the captured demo output. showboats verify step re-executes every exec block in docs/demos/wt-c2-mcp-rebuild/demo.md byte-exactly; the regenerated demo.md carries no reference to :61244."

uvx showboat exec "$DEMO_FILE" bash '
set -euo pipefail
if grep -q "61244" docs/demos/wt-c2-mcp-rebuild/demo.md; then
  echo "FAIL: 61244 still appears in the captured demo.md"
  exit 1
else
  echo "OK: no 61244 reference in docs/demos/wt-c2-mcp-rebuild/demo.md"
fi
'

uvx showboat note "$DEMO_FILE" \
  "Proof 3 — showboat verify on the patched c2 demo passes. We run verify in a subshell and capture only the exit code (verify output contains timestamps, which would break byte-exact re-verification of THIS demo)."

uvx showboat exec "$DEMO_FILE" bash '
set -euo pipefail
if uvx showboat verify docs/demos/wt-c2-mcp-rebuild/demo.md >/dev/null 2>&1; then
  echo "OK: uvx showboat verify docs/demos/wt-c2-mcp-rebuild/demo.md exit=0"
else
  echo "FAIL: showboat verify on patched c2 demo returned non-zero"
  exit 1
fi
'

uvx showboat verify "$DEMO_FILE"
