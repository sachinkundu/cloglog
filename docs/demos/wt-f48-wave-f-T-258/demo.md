# /api/v1/projects/{id}/worktrees keeps its auth requirement (Option B) and is now advertised loudly — route docstring, doc cross-links, explicit dashboard-key guards in CLI and in-tree scripts, and E2E regression tests (T-258).

*2026-04-23T07:00:42Z by Showboat 0.6.1*
<!-- showboat-id: e3f5a025-01cd-4493-9bbc-b04f7a643efd -->

Before: the auth contract on /api/v1/projects/{id}/worktrees was implicit. src/gateway/cli.py and scripts/sync_mcp_dist.py relied on env-passthrough of the dashboard key through _auth_headers; a caller that forgot CLOGLOG_API_KEY got a cryptic remote 401. Codex flagged the ambiguity during PR #172 review.

After (Option B — locked by user): the route stays authed, every caller passes the header explicitly, and every contract element is either in code or covered by a regression test.

Proof 1 — route docstring. src/agent/routes.py::list_worktrees now carries an AUTH block that names the middleware and lists the three accepted credential shapes. Per-file boolean, scoped to the exact file under audit.

```bash

set -euo pipefail
if grep -q "AUTH: NOT a public route" src/agent/routes.py; then
  echo "OK: AUTH docstring present on list_worktrees"
else
  echo "FAIL: list_worktrees AUTH docstring missing"
  exit 1
fi

```

```output
OK: AUTH docstring present on list_worktrees
```

Proof 2 — doc cross-links. docs/ddd-context-map.md and docs/design.md both have an Auth Contract section that pins the /worktrees route with its credential requirement.

```bash

set -euo pipefail
if grep -q "^## Auth Contract" docs/ddd-context-map.md; then
  echo "OK: docs/ddd-context-map.md has Auth Contract section"
else
  echo "FAIL: Auth Contract section missing from docs/ddd-context-map.md"
  exit 1
fi
if grep -q "Auth Contract" docs/design.md; then
  echo "OK: docs/design.md references Auth Contract"
else
  echo "FAIL: docs/design.md does not reference Auth Contract"
  exit 1
fi

```

```output
OK: docs/ddd-context-map.md has Auth Contract section
OK: docs/design.md references Auth Contract
```

Proof 3 — CLI guards the dashboard key at the call site. Both _resolve_worktree and agents_list call _require_dashboard_key before the HTTP call, so callers without CLOGLOG_API_KEY get a local error that names the operation and the env var, not a cryptic remote 401.

```bash

set -euo pipefail
count=$(grep -c "_require_dashboard_key" src/gateway/cli.py)
# Expect: 1 def line + 2 call sites (_resolve_worktree, agents_list) + 1 docstring mention = at least 4
if [ "$count" -ge 4 ]; then
  echo "OK: src/gateway/cli.py references _require_dashboard_key in $count locations"
else
  echo "FAIL: expected >=4 references to _require_dashboard_key, found $count"
  exit 1
fi

```

```output
OK: src/gateway/cli.py references _require_dashboard_key in 5 locations
```

Proof 4 — sync_mcp_dist.py is explicit too. Sends X-Dashboard-Key and calls raise_for_status() so a future 403 surfaces instead of silently returning an empty list.

```bash

set -euo pipefail
if grep -q "X-Dashboard-Key" scripts/sync_mcp_dist.py && grep -q "raise_for_status" scripts/sync_mcp_dist.py; then
  echo "OK: scripts/sync_mcp_dist.py sends X-Dashboard-Key and calls raise_for_status"
else
  echo "FAIL: scripts/sync_mcp_dist.py missing explicit auth header or raise_for_status"
  exit 1
fi

```

```output
OK: scripts/sync_mcp_dist.py sends X-Dashboard-Key and calls raise_for_status
```

Proof 5 — the four new E2E regression tests exist and cover every credential shape on this route. Next time someone wants to flip /worktrees to a public route they must update these first — the tests are the contract.

```bash

set -euo pipefail
needed=(
  test_worktrees_without_auth_is_rejected
  test_worktrees_with_wrong_dashboard_key_is_rejected
  test_worktrees_with_dashboard_key_succeeds
  test_worktrees_with_agent_token_is_rejected
)
missing=()
for name in "${needed[@]}"; do
  grep -q "def ${name}" tests/e2e/test_access_control.py || missing+=("$name")
done
if [ ${#missing[@]} -eq 0 ]; then
  echo "OK: all 4 T-258 regression tests present in tests/e2e/test_access_control.py"
else
  echo "FAIL: missing tests: ${missing[*]}"
  exit 1
fi

```

```output
OK: all 4 T-258 regression tests present in tests/e2e/test_access_control.py
```
