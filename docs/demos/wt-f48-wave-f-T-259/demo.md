# Worktree bootstrap resolves backend_url from .cloglog/config.yaml via grep+sed, so close-off-task creation no longer silently targets :8000 on hosts without pyyaml (T-259).

*2026-04-22T17:24:14Z by Showboat 0.6.1*
<!-- showboat-id: 87caefb1-1906-46cf-8fd6-aeacad4ab53f -->

Before: .cloglog/on-worktree-create.sh's _resolve_backend_url used a 'python3 -c import yaml' snippet that silently returned http://localhost:8000 when pyyaml was missing. The subsequent close-off-task POST landed on :8000 instead of the configured port; curl returned a non-fatal WARN and no board task was ever created — but nothing failed loudly.

Fix: _resolve_backend_url now uses the same grep+sed pattern as plugins/cloglog/hooks/agent-shutdown.sh:62-74. The hook also logs the resolved URL to stderr unconditionally so a silent fallback cannot hide. A pytest regression guard (test_hook_does_not_invoke_python_yaml) pins the CLAUDE.md rule at the source level.

Case 1 — config declares http://127.0.0.1:8001; the hook must resolve EXACTLY that URL, not localhost:8000. We build a hermetic scratch repo with a stub worktree-infra.sh, invoke the hook with an empty HOME so the curl block is skipped, and capture only the one deterministic line out of stderr.

```bash

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

```

```output
[on-worktree-create] backend_url=http://127.0.0.1:8001
```

Case 2 — config omits backend_url entirely; the hook falls back to the documented http://localhost:8000 default. Same harness.

```bash

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

```

```output
[on-worktree-create] backend_url=http://localhost:8000
```

Case 3 — source-level guard. The anti-pattern must not appear on any non-comment line of .cloglog/on-worktree-create.sh. Per-file boolean (not a repo-wide count) so an unrelated future doc that mentions the same identifier will never flip this demo.

```bash

if grep -v "^[[:space:]]*#" .cloglog/on-worktree-create.sh | grep -qE "import yaml|yaml\.safe_load"; then
  echo "FAIL: yaml import found in non-comment lines"
  exit 1
else
  echo "OK: no yaml import in non-comment lines of .cloglog/on-worktree-create.sh"
fi

```

```output
OK: no yaml import in non-comment lines of .cloglog/on-worktree-create.sh
```
