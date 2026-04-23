#!/usr/bin/env bash
# Demo: T-257 — .cloglog/on-worktree-create.sh now installs mcp-server
# node_modules on ANY worktree whose checkout has mcp-server/package.json,
# not only wt-mcp* branches. Prior guard silently skipped the install on
# wt-c2-mcp-rebuild and every `make quality` after that failed on npx tsc.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

# Self-locate the demo dir to avoid the branch-name path bug from T-259
# codex round 1.
DEMO_DIR="${SCRIPT_DIR#"$REPO_ROOT"/}"
DEMO_FILE="$DEMO_DIR/demo.md"

rm -f "$DEMO_FILE"

uvx showboat init "$DEMO_FILE" \
  "Worktree bootstrap now installs mcp-server/ deps whenever mcp-server/package.json exists — no more silent skip on worktrees whose name does not match wt-mcp* (T-257)."

uvx showboat note "$DEMO_FILE" \
  "Before: .cloglog/on-worktree-create.sh gated the install on WORKTREE_NAME == wt-mcp* AND -d mcp-server. Any worktree that needed to touch mcp-server but was named differently (e.g. wt-c2-mcp-rebuild during T-244) shipped without node_modules; the first make quality failed on 'npx tsc: This is not the tsc command you are looking for' because the compiler was absent."

uvx showboat note "$DEMO_FILE" \
  "After: the guard is now just -f mcp-server/package.json. Install fires on every worktree whose checkout has the manifest, regardless of branch name. Downstream projects using this plugin without an MCP server skip cleanly because they have no package.json."

uvx showboat note "$DEMO_FILE" \
  "Case 1 — the scenario T-244 hit. WORKTREE_NAME=wt-c2-mcp-rebuild (does NOT match wt-mcp*), mcp-server/package.json exists in the worktree. The hook MUST call npm install. We PATH-shim npm to a stub that records argv so the test is hermetic."

uvx showboat exec "$DEMO_FILE" bash '
set -euo pipefail
t=$(mktemp -d)
mkdir -p "$t/repo/.cloglog" "$t/repo/scripts" "$t/wt/mcp-server" "$t/shim"
cp .cloglog/on-worktree-create.sh "$t/repo/.cloglog/"
printf "project: demo\n" > "$t/repo/.cloglog/config.yaml"
printf "#!/bin/bash\nexit 0\n" > "$t/repo/scripts/worktree-infra.sh"
chmod +x "$t/repo/scripts/worktree-infra.sh"
printf "{\"name\":\"test-mcp\",\"version\":\"0.0.0\"}\n" > "$t/wt/mcp-server/package.json"
NPM_LOG="$t/npm.log"
printf "#!/bin/bash\nprintf \"npm %%s\\n\" \"\$*\" >> \"\$NPM_LOG\"\nexit 0\n" > "$t/shim/npm"
chmod +x "$t/shim/npm"
env -u CLOGLOG_API_KEY PATH="$t/shim:$PATH" HOME="$t/empty-home" \
    WORKTREE_PATH="$t/wt" WORKTREE_NAME=wt-c2-mcp-rebuild NPM_LOG="$NPM_LOG" \
  bash "$t/repo/.cloglog/on-worktree-create.sh" >/dev/null 2>&1
printf "npm invocations: "
if [[ -f "$NPM_LOG" ]]; then cat "$NPM_LOG"; else echo "(none)"; fi
'

uvx showboat note "$DEMO_FILE" \
  "Case 2 — legacy wt-mcp* branches still trigger the install. T-257 only broadens, never narrows. Same stub harness."

uvx showboat exec "$DEMO_FILE" bash '
set -euo pipefail
t=$(mktemp -d)
mkdir -p "$t/repo/.cloglog" "$t/repo/scripts" "$t/wt/mcp-server" "$t/shim"
cp .cloglog/on-worktree-create.sh "$t/repo/.cloglog/"
printf "project: demo\n" > "$t/repo/.cloglog/config.yaml"
printf "#!/bin/bash\nexit 0\n" > "$t/repo/scripts/worktree-infra.sh"
chmod +x "$t/repo/scripts/worktree-infra.sh"
printf "{\"name\":\"test-mcp\",\"version\":\"0.0.0\"}\n" > "$t/wt/mcp-server/package.json"
NPM_LOG="$t/npm.log"
printf "#!/bin/bash\nprintf \"npm %%s\\n\" \"\$*\" >> \"\$NPM_LOG\"\nexit 0\n" > "$t/shim/npm"
chmod +x "$t/shim/npm"
env -u CLOGLOG_API_KEY PATH="$t/shim:$PATH" HOME="$t/empty-home" \
    WORKTREE_PATH="$t/wt" WORKTREE_NAME=wt-mcp-rebuild NPM_LOG="$NPM_LOG" \
  bash "$t/repo/.cloglog/on-worktree-create.sh" >/dev/null 2>&1
printf "npm invocations: "
if [[ -f "$NPM_LOG" ]]; then cat "$NPM_LOG"; else echo "(none)"; fi
'

uvx showboat note "$DEMO_FILE" \
  "Case 3 — downstream project with no mcp-server/ directory. The manifest guard keeps these projects quiet; no spurious npm call."

uvx showboat exec "$DEMO_FILE" bash '
set -euo pipefail
t=$(mktemp -d)
mkdir -p "$t/repo/.cloglog" "$t/repo/scripts" "$t/wt" "$t/shim"
cp .cloglog/on-worktree-create.sh "$t/repo/.cloglog/"
printf "project: demo\n" > "$t/repo/.cloglog/config.yaml"
printf "#!/bin/bash\nexit 0\n" > "$t/repo/scripts/worktree-infra.sh"
chmod +x "$t/repo/scripts/worktree-infra.sh"
NPM_LOG="$t/npm.log"
printf "#!/bin/bash\nprintf \"npm %%s\\n\" \"\$*\" >> \"\$NPM_LOG\"\nexit 0\n" > "$t/shim/npm"
chmod +x "$t/shim/npm"
env -u CLOGLOG_API_KEY PATH="$t/shim:$PATH" HOME="$t/empty-home" \
    WORKTREE_PATH="$t/wt" WORKTREE_NAME=wt-anything NPM_LOG="$NPM_LOG" \
  bash "$t/repo/.cloglog/on-worktree-create.sh" >/dev/null 2>&1
if [[ -s "$NPM_LOG" ]]; then
  echo "FAIL: npm invoked on worktree without mcp-server/:"
  cat "$NPM_LOG"
  exit 1
else
  echo "OK: no npm invocation when mcp-server/ is absent"
fi
'

uvx showboat verify "$DEMO_FILE"
