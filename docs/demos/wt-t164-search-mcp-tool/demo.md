# Agents can now resolve T-NNN, F-NN, E-N references and free-text queries through mcp__cloglog__search — a thin wrapper over the existing GET /api/v1/projects/{id}/search endpoint, so behaviour matches the CLI's _resolve_task path exactly without paging the full board.

*2026-04-26T09:30:59Z by Showboat 0.6.1*
<!-- showboat-id: 9c61568e-0c30-4373-b679-b444d54f6671 -->

Proof 1 — search tool is registered in the source-of-truth server.ts at the same arg position as every other server.tool call.

```bash
SERVER=mcp-server/src/server.ts
   has_search=$(grep -cE "^ *'search'," "$SERVER")
   echo "search_tool_registered=$( [[ $has_search -eq 1 ]] && echo OK || echo FAIL )"
```

```output
search_tool_registered=OK
```

Proof 2 — handler in src/tools.ts targets /projects/{id}/search and the URL parity with src/gateway/cli.py is pinned (matching shape: ?q=… on the same path).

```bash
TOOLS=mcp-server/src/tools.ts
   CLI=src/gateway/cli.py
   has_search_path=$(grep -cE "/projects/\\\${project_id}/search" "$TOOLS")
   cli_uses_search=$(grep -cE "/projects/\{project_id\}/search" "$CLI")
   echo "handler_uses_project_search_path=$( [[ $has_search_path -ge 1 ]] && echo OK || echo FAIL )"
   echo "cli_uses_same_endpoint=$( [[ $cli_uses_search -ge 1 ]] && echo OK || echo FAIL )"
```

```output
handler_uses_project_search_path=OK
cli_uses_same_endpoint=OK
```

Proof 3 — handler URL construction is byte-exact for the three documented call shapes. The vitest cases that pin them (entity number → ?q=T-42, free text → URL-encoded q, limit + multi status_filter → repeated query keys) all pass; output reduced to a count so verify is deterministic.

```bash
cd mcp-server && npx vitest run --reporter=basic src/__tests__/tools.test.ts -t search 2>&1 \
     | grep -oE "Tests  [0-9]+ passed" | head -1
```

```output
Tests  3 passed
```

Proof 4 — backend route the wrapper depends on still lives at GET /api/v1/projects/{project_id}/search.

```bash
ROUTES=src/board/routes.py
   has_route=$(grep -c "/projects/{project_id}/search" "$ROUTES")
   has_get=$(grep -B1 "/projects/{project_id}/search" "$ROUTES" | grep -c "router.get")
   echo "backend_route_present=$( [[ $has_route -ge 1 ]] && echo OK || echo FAIL )"
   echo "backend_route_is_GET=$( [[ $has_get -ge 1 ]] && echo OK || echo FAIL )"
```

```output
backend_route_present=OK
backend_route_is_GET=OK
```

Proof 5 — MCP-server vitest suite passes (handler URL pins + server tool registration + pre-register guard).

```bash
cd mcp-server && npx vitest run --reporter=basic 2>&1 \
     | grep -oE "Tests  [0-9]+ passed" | head -1
```

```output
Tests  88 passed
```
