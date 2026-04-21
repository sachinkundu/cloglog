# The main agent can now ask a worktree to shut down gracefully via mcp__cloglog__request_shutdown, and (tier-2) forcibly remove a wedged worktree via mcp__cloglog__force_unregister — with auth that explicitly refuses agent tokens so a wedged agent cannot self-unregister.

*2026-04-21T08:12:48Z by Showboat 0.6.1*
<!-- showboat-id: 0ca1f410-4ee7-414b-ad4d-5c7e46988aae -->

T-218+T-221 proof 1 — both tools are registered in the compiled MCP server dist. Output: one OK per tool.

```bash
SERVER=mcp-server/dist/server.js
   # tsc emits server.tool(\x27request_shutdown\x27, ...) — match the registration site literally.
   has_request=$(grep -c "server.tool(.request_shutdown." "$SERVER")
   has_force=$(grep -c "server.tool(.force_unregister." "$SERVER")
   echo "request_shutdown_registered=$( [[ $has_request -ge 1 ]] && echo OK || echo FAIL )"
   echo "force_unregister_registered=$( [[ $has_force -ge 1 ]] && echo OK || echo FAIL )"
```

```output
request_shutdown_registered=OK
force_unregister_registered=OK
```

T-218+T-221 proof 2 — tool handlers in dist/tools.js POST to the correct backend paths. Output: one OK per tool.

```bash
TOOLS=mcp-server/dist/tools.js
   has_req_path=$(grep -c "/request-shutdown" "$TOOLS")
   has_force_path=$(grep -c "/force-unregister" "$TOOLS")
   echo "request_shutdown_path_wired=$( [[ $has_req_path -ge 1 ]] && echo OK || echo FAIL )"
   echo "force_unregister_path_wired=$( [[ $has_force_path -ge 1 ]] && echo OK || echo FAIL )"
```

```output
request_shutdown_path_wired=OK
force_unregister_path_wired=OK
```

T-218+T-221 proof 3 — the compiled client.js recognises both new endpoints as supervisor routes (so they ride the MCP service key rather than the caller's agent token).

```bash
CLIENT=mcp-server/dist/client.js
   has_req=$(grep -c "/request-shutdown" "$CLIENT")
   has_force=$(grep -c "/force-unregister" "$CLIENT")
   echo "supervisor_routes_contain_request_shutdown=$( [[ $has_req -ge 1 ]] && echo OK || echo FAIL )"
   echo "supervisor_routes_contain_force_unregister=$( [[ $has_force -ge 1 ]] && echo OK || echo FAIL )"
```

```output
supervisor_routes_contain_request_shutdown=OK
supervisor_routes_contain_force_unregister=OK
```

T-221 proof 4 — force_unregister's MCP tool description marks it as tier-2 and tells the caller to try request_shutdown first. If this wording drifts, T-220 reconcile will happily skip the graceful lever.

```bash
SERVER=mcp-server/dist/server.js
   c_tier=$(grep -c "TIER-2\|tier-2" "$SERVER")
   c_call_first=$(grep -c "call request_shutdown first\|request_shutdown first" "$SERVER")
   echo "tier2_label_present=$( [[ $c_tier -ge 1 ]] && echo OK || echo FAIL )"
   echo "request_shutdown_first_hint=$( [[ $c_call_first -ge 1 ]] && echo OK || echo FAIL )"
```

```output
tier2_label_present=OK
request_shutdown_first_hint=OK
```

T-221 proof 5 — the backend route uses the new McpOrProject dependency (not SupervisorAuth, which would allow the target agent's own token). Booleans read directly off src/agent/routes.py and src/gateway/auth.py.

```bash
ROUTES=src/agent/routes.py
   AUTH=src/gateway/auth.py
   has_route=$(grep -c "/agents/{worktree_id}/force-unregister" "$ROUTES")
   uses_mcp_or_project=$(grep -c "McpOrProject" "$ROUTES")
   has_dep=$(grep -c "def get_mcp_or_project" "$AUTH")
   rejects_agent=$(grep -c "agent tokens are not accepted" "$AUTH")
   echo "route_registered=$( [[ $has_route -ge 1 ]] && echo OK || echo FAIL )"
   echo "route_uses_McpOrProject=$( [[ $uses_mcp_or_project -ge 1 ]] && echo OK || echo FAIL )"
   echo "auth_dep_defined=$( [[ $has_dep -ge 1 ]] && echo OK || echo FAIL )"
   echo "auth_dep_rejects_agent_tokens=$( [[ $rejects_agent -ge 1 ]] && echo OK || echo FAIL )"
```

```output
route_registered=OK
route_uses_McpOrProject=OK
auth_dep_defined=OK
auth_dep_rejects_agent_tokens=OK
```

T-221 proof 6 — the service emits a grep-able audit line on every call. Pinning the exact token (audit=force_unregister) means a supervisor can cat-and-grep the logs without knowing Python logging internals.

```bash
SERVICES=src/agent/services.py
   has_audit_token=$(grep -c "audit=force_unregister" "$SERVICES")
   has_caller_field=$(grep -c "caller_project_id=" "$SERVICES")
   has_already_field=$(grep -c "already_unregistered=" "$SERVICES")
   echo "audit_token_present=$( [[ $has_audit_token -ge 1 ]] && echo OK || echo FAIL )"
   echo "caller_project_field_logged=$( [[ $has_caller_field -ge 1 ]] && echo OK || echo FAIL )"
   echo "idempotency_field_logged=$( [[ $has_already_field -ge 1 ]] && echo OK || echo FAIL )"
```

```output
audit_token_present=OK
caller_project_field_logged=OK
idempotency_field_logged=OK
```

Contract proof — both endpoints are declared in the baseline OpenAPI contract and the runtime FastAPI schema matches. The second line is the live backend check (exit code surfaced as OK/FAIL).

```bash
CONTRACT=docs/contracts/baseline.openapi.yaml
   has_req=$(grep -c "/api/v1/agents/{worktree_id}/request-shutdown:" "$CONTRACT")
   has_force=$(grep -c "/api/v1/agents/{worktree_id}/force-unregister:" "$CONTRACT")
   echo "request_shutdown_in_contract=$( [[ $has_req -eq 1 ]] && echo OK || echo FAIL )"
   echo "force_unregister_in_contract=$( [[ $has_force -eq 1 ]] && echo OK || echo FAIL )"
   if make -s contract-check >/dev/null 2>&1; then
     echo "runtime_contract_check=OK"
   else
     echo "runtime_contract_check=FAIL"
   fi
```

```output
request_shutdown_in_contract=OK
force_unregister_in_contract=OK
runtime_contract_check=OK
```

Backend behaviour proof — the 7 new force-unregister integration tests pass. Each covers one stated contract: success, idempotent second call, unknown-id idempotency, cross-project 403, agent-token rejection, MCP-service-key acceptance, audit log presence. Output reduced to a single PASSED count.

```bash
uv run pytest tests/agent/test_integration.py::TestForceUnregisterAPI -q 2>&1 \
     | grep -oE "[0-9]+ passed" | head -1
```

```output
7 passed
```

MCP-server behaviour proof — Vitest runs for the new tools pass. Reduces to "Tests  N passed" so verify is byte-exact.

```bash
cd mcp-server && npx vitest run --reporter=basic 2>&1 \
     | grep -oE "Tests  [0-9]+ passed" | head -1
```

```output
Tests  77 passed
```
