#!/usr/bin/env bash
# Demo: T-259 — _resolve_backend_url in .cloglog/on-worktree-create.sh now
# parses backend_url via grep+sed instead of `python3 -c 'import yaml'`, so
# the close-off-task POST lands on the configured port even on hosts where
# the system python3 lacks pyyaml.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

# Derive DEMO_DIR from the script's own location, NOT from `git rev-parse`.
# The original version used `docs/demos/${BRANCH//\//-}-T-259` which appended
# a literal `-T-259` suffix to whatever branch the script ran from —
# brittle under rename (e.g. close-off branches) and a convention deviation
# from docs/demos/wt-d2-close-off-template/demo-script.sh. Since this
# script lives at `docs/demos/wt-f48-wave-f-T-259/demo-script.sh`, the
# committed demo.md and the regenerated demo.md always agree. Caught in
# codex review of PR #186.
DEMO_DIR="${SCRIPT_DIR#"$REPO_ROOT"/}"
DEMO_FILE="$DEMO_DIR/demo.md"

# showboat init refuses to overwrite — rm first so `make demo` is re-runnable.
rm -f "$DEMO_FILE"

uvx showboat init "$DEMO_FILE" \
  "Worktree bootstrap resolves backend_url from .cloglog/config.yaml via grep+sed, so close-off-task creation no longer silently targets :8000 on hosts without pyyaml (T-259)."

uvx showboat note "$DEMO_FILE" \
  "Before: .cloglog/on-worktree-create.sh's _resolve_backend_url used a 'python3 -c import yaml' snippet that silently returned http://localhost:8000 when pyyaml was missing. The subsequent close-off-task POST landed on :8000 instead of the configured port; curl returned a non-fatal WARN and no board task was ever created — but nothing failed loudly."

uvx showboat note "$DEMO_FILE" \
  "Fix: _resolve_backend_url now uses the same grep+sed pattern as plugins/cloglog/hooks/agent-shutdown.sh:62-74. The hook also logs the resolved URL to stderr unconditionally so a silent fallback cannot hide. A pytest regression guard (test_hook_does_not_invoke_python_yaml) pins the CLAUDE.md rule at the source level."

uvx showboat note "$DEMO_FILE" \
  "Case 1 — config declares http://127.0.0.1:8001; the hook must resolve EXACTLY that URL, not localhost:8000. We build a hermetic scratch repo with a stub worktree-infra.sh, invoke the hook with an empty HOME so the curl block is skipped, and capture only the one deterministic line out of stderr."

uvx showboat exec "$DEMO_FILE" bash '
set -euo pipefail
t=$(mktemp -d)
mkdir -p "$t/repo/.cloglog" "$t/repo/scripts" "$t/wt"
cp .cloglog/on-worktree-create.sh "$t/repo/.cloglog/"
printf "project: demo\nbackend_url: http://127.0.0.1:8001\n" > "$t/repo/.cloglog/config.yaml"
printf "#!/bin/bash\nexit 0\n" > "$t/repo/scripts/worktree-infra.sh"
chmod +x "$t/repo/scripts/worktree-infra.sh"
env -u CLOGLOG_API_KEY HOME="$t/empty-home" WORKTREE_PATH="$t/wt" WORKTREE_NAME=wt-demo \
  bash "$t/repo/.cloglog/on-worktree-create.sh" 2>&1 \
  | grep "^\[on-worktree-create\] backend_url="
'

uvx showboat note "$DEMO_FILE" \
  "Case 2 — config omits backend_url entirely; the hook falls back to the documented http://localhost:8000 default. Same harness."

uvx showboat exec "$DEMO_FILE" bash '
set -euo pipefail
t=$(mktemp -d)
mkdir -p "$t/repo/.cloglog" "$t/repo/scripts" "$t/wt"
cp .cloglog/on-worktree-create.sh "$t/repo/.cloglog/"
printf "project: demo\n" > "$t/repo/.cloglog/config.yaml"
printf "#!/bin/bash\nexit 0\n" > "$t/repo/scripts/worktree-infra.sh"
chmod +x "$t/repo/scripts/worktree-infra.sh"
env -u CLOGLOG_API_KEY HOME="$t/empty-home" WORKTREE_PATH="$t/wt" WORKTREE_NAME=wt-demo \
  bash "$t/repo/.cloglog/on-worktree-create.sh" 2>&1 \
  | grep "^\[on-worktree-create\] backend_url="
'

uvx showboat note "$DEMO_FILE" \
  'Case 3 — source-level guard. The anti-pattern must not appear on any non-comment line of .cloglog/on-worktree-create.sh. Per-file boolean (not a repo-wide count) so an unrelated future doc that mentions the same identifier will never flip this demo.'

uvx showboat exec "$DEMO_FILE" bash '
if grep -v "^[[:space:]]*#" .cloglog/on-worktree-create.sh | grep -qE "import yaml|yaml\.safe_load"; then
  echo "FAIL: yaml import found in non-comment lines"
  exit 1
else
  echo "OK: no yaml import in non-comment lines of .cloglog/on-worktree-create.sh"
fi
'

uvx showboat verify "$DEMO_FILE"
