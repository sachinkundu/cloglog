# The main agent can now ask a worktree to shut down gracefully via mcp__cloglog__request_shutdown, and (tier-2) forcibly remove a wedged worktree via mcp__cloglog__force_unregister — with auth that explicitly refuses agent tokens so a wedged agent cannot self-unregister.

*2026-04-21T08:26:56Z by Showboat 0.6.1*
<!-- showboat-id: b1eec215-9376-45ac-a4d4-0a77371345bd -->

T-218+T-221 proof 1 — both tools are registered in mcp-server/src/server.ts. Output: one OK per tool.

```bash
SERVER=mcp-server/src/server.ts
   # tsc emits server.tool registrations that span multiple lines in source,
   # so match the tool-name literal on its own (the argument position is
   # unambiguous because the only other spot request_shutdown could live is
   # as a prose reference — counted separately by proof 4).
   has_request=$(grep -cE "^ *'request_shutdown'," "$SERVER")
   has_force=$(grep -cE "^ *'force_unregister'," "$SERVER")
   echo "request_shutdown_registered=$( [[ $has_request -eq 1 ]] && echo OK || echo FAIL )"
   echo "force_unregister_registered=$( [[ $has_force -eq 1 ]] && echo OK || echo FAIL )"
```

```output
request_shutdown_registered=OK
force_unregister_registered=OK
```

T-218+T-221 proof 2 — tool handlers in src/tools.ts POST to the correct backend paths. Output: one OK per tool.

```bash
TOOLS=mcp-server/src/tools.ts
   has_req_path=$(grep -c "/request-shutdown" "$TOOLS")
   has_force_path=$(grep -c "/force-unregister" "$TOOLS")
   echo "request_shutdown_path_wired=$( [[ $has_req_path -ge 1 ]] && echo OK || echo FAIL )"
   echo "force_unregister_path_wired=$( [[ $has_force_path -ge 1 ]] && echo OK || echo FAIL )"
```

```output
request_shutdown_path_wired=OK
force_unregister_path_wired=OK
```

T-218+T-221 proof 3 — mcp-server/src/client.ts lists both new endpoints as supervisor routes (so they ride the MCP service key rather than the caller's agent token).

```bash
CLIENT=mcp-server/src/client.ts
   has_req=$(grep -c "/request-shutdown" "$CLIENT")
   has_force=$(grep -c "/force-unregister" "$CLIENT")
   in_list=$(grep -c "SUPERVISOR_SUFFIXES" "$CLIENT")
   echo "supervisor_routes_contain_request_shutdown=$( [[ $has_req -ge 1 ]] && echo OK || echo FAIL )"
   echo "supervisor_routes_contain_force_unregister=$( [[ $has_force -ge 1 ]] && echo OK || echo FAIL )"
   echo "supervisor_list_defined=$( [[ $in_list -ge 1 ]] && echo OK || echo FAIL )"
```

```output
supervisor_routes_contain_request_shutdown=OK
supervisor_routes_contain_force_unregister=OK
supervisor_list_defined=OK
```

T-221 proof 4 — force_unregister's MCP tool description marks it as tier-2 and tells the caller to try request_shutdown first. If this wording drifts, T-220 reconcile will happily skip the graceful lever.

```bash
SERVER=mcp-server/src/server.ts
   c_tier=$(grep -c "TIER-2\|tier-2" "$SERVER")
   c_call_first=$(grep -c "call request_shutdown first\|request_shutdown first" "$SERVER")
   echo "tier2_label_present=$( [[ $c_tier -ge 1 ]] && echo OK || echo FAIL )"
   echo "request_shutdown_first_hint=$( [[ $c_call_first -ge 1 ]] && echo OK || echo FAIL )"
```

```output
tier2_label_present=OK
request_shutdown_first_hint=OK
```

T-221 proof 5 — the force-unregister route uses the new McpOrProject dependency (not SupervisorAuth, which would allow the target agent's own token). Booleans read directly off src/agent/routes.py and src/gateway/auth.py.

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

T-218 proof 5b — request_shutdown route is guarded by SupervisorAuth and the regression test covering the invalid-token attack is present.

```bash
ROUTES=src/agent/routes.py
   TESTS=tests/agent/test_integration.py
   req_sig=$(grep -c "async def request_shutdown(" "$ROUTES")
   req_auth=$(grep -A2 "async def request_shutdown(" "$ROUTES" | grep -c "SupervisorAuth")
   regr_test=$(grep -c "test_request_shutdown_invalid_token_rejected" "$TESTS")
   cross_test=$(grep -c "test_request_shutdown_cross_project_forbidden" "$TESTS")
   echo "request_shutdown_defined=$( [[ $req_sig -eq 1 ]] && echo OK || echo FAIL )"
   echo "request_shutdown_uses_SupervisorAuth=$( [[ $req_auth -ge 1 ]] && echo OK || echo FAIL )"
   echo "invalid_token_regression_test_present=$( [[ $regr_test -eq 1 ]] && echo OK || echo FAIL )"
   echo "cross_project_test_present=$( [[ $cross_test -eq 1 ]] && echo OK || echo FAIL )"
```

```output
request_shutdown_defined=OK
request_shutdown_uses_SupervisorAuth=OK
invalid_token_regression_test_present=OK
cross_project_test_present=OK
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

Backend behaviour proof — the combined shutdown + force-unregister integration suites pass. Covers: request_shutdown success, empty-path 409, invalid-token 401 (regression), cross-project 403, MCP-service-key 200, force_unregister success, idempotent second call, unknown-id idempotency, cross-project 403, agent-token rejection, MCP-service-key 200, audit log presence. Output reduced to a single PASSED count so verify is byte-exact.

```bash
uv run pytest tests/agent/test_integration.py::TestRequestShutdownAPI tests/agent/test_integration.py::TestForceUnregisterAPI -q 2>&1 \
     | grep -oE "[0-9]+ passed" | head -1
```

```output
12 passed
```

MCP-server behaviour proof — Vitest runs for the new tools pass. Reduces to "Tests  N passed" so verify is byte-exact.

```bash
cd mcp-server && npx vitest run --reporter=basic 2>&1 \
     | grep -oE "Tests  [0-9]+ passed" | head -1
```

```output
Tests  77 passed
```
