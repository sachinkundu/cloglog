#!/usr/bin/env bash
# Close-wave demo for F-48 Wave F: verify all four task PRs merged and
# the security regression (list_worktrees accepting any MCP bearer) is
# closed with a regression test on main.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

DEMO_DIR="${SCRIPT_DIR#"$REPO_ROOT"/}"
DEMO_FILE="$DEMO_DIR/demo.md"

rm -f "$DEMO_FILE"

uvx showboat init "$DEMO_FILE" \
  "Close-wave for F-48 Wave F — four agent-lifecycle-hardening PRs merged (T-259, T-257, T-256, T-258); the dormant list_worktrees auth hole caught by codex round 2 on PR #191 is now pinned by a regression test."

uvx showboat note "$DEMO_FILE" \
  "PRs merged in this wave: #186 T-259 (backend_url grep+sed), #188 T-257 (broaden npm-install trigger), #189 T-256 (demo port 0), #191 T-258 (worktrees auth contract Option B). Agent wt-f48-wave-f cooperative-unregistered at 2026-04-23T10:23:53+03:00 after all four PRs merged."

uvx showboat note "$DEMO_FILE" \
  "Proof 1 — origin/main carries the four merge commits in order (PR #186, #188, #189, #191). Verified via git log oneline grep."

uvx showboat exec "$DEMO_FILE" bash '
count=$(git log --oneline origin/main 2>/dev/null | grep -cE "Merge pull request #(186|188|189|191)")
if [ "$count" -eq 4 ]; then echo "OK all 4 F-48 Wave F PRs on main"; else echo "FAIL expected 4 merge commits on main, got $count"; exit 1; fi
'

uvx showboat note "$DEMO_FILE" \
  "Proof 2 — list_worktrees now requires an MCP-service or dashboard credential (PR #191 round 2 security fix). Route source shows the per-route Depends is in place."

uvx showboat exec "$DEMO_FILE" bash '
python3 - <<PY
import pathlib
src = pathlib.Path("src/agent/routes.py").read_text()
assert "CurrentMcpOrDashboard" in src, "CurrentMcpOrDashboard dep missing from agent routes"
# list_worktrees must declare the dep
blocks = src.split("def ")
found = False
for b in blocks:
    if b.startswith("list_worktrees"):
        found = "CurrentMcpOrDashboard" in b
        break
assert found, "list_worktrees must declare CurrentMcpOrDashboard Depends"
print("OK list_worktrees declares CurrentMcpOrDashboard dep")
PY
'

uvx showboat note "$DEMO_FILE" \
  "Proof 3 — regression test pins the invalid-bearer behaviour. Any new non-agent route regressing this invariant will now fail in test."

uvx showboat exec "$DEMO_FILE" bash '
python3 - <<PY
import pathlib
tests = pathlib.Path("tests/e2e/test_access_control.py").read_text()
assert "test_worktrees_with_invalid_mcp_bearer_is_rejected" in tests, "regression test test_worktrees_with_invalid_mcp_bearer_is_rejected missing"
print("OK test_access_control pins the list_worktrees invalid-bearer case")
PY
'

uvx showboat note "$DEMO_FILE" \
  "Proof 4 — CLAUDE.md now carries the authoritative rule: non-agent routes accepting MCP credentials MUST declare CurrentMcpService/CurrentMcpOrDashboard as Depends. Future waves will read this before adding new routes."

uvx showboat exec "$DEMO_FILE" bash '
grep -q "CurrentMcpService.*CurrentMcpOrDashboard.*Depends" CLAUDE.md \
  || grep -q "Non-agent routes accepting MCP credentials" CLAUDE.md
echo "OK CLAUDE.md rule present"
'

uvx showboat verify "$DEMO_FILE"
