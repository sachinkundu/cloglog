# Fix: MCP Server Route Isolation Bypass

*2026-04-06T11:41:12Z by Showboat 0.6.1*
<!-- showboat-id: 5c9ed232-9440-4aeb-9fd5-e554d6591563 -->

MCP server (with X-MCP-Request header) can access board routes. Direct agent calls (no MCP header) are still blocked.

```python3

import urllib.request, json

# MCP server call: API key + X-MCP-Request header → ALLOWED
req = urllib.request.Request(
    'http://localhost:8000/api/v1/projects',
    headers={'Authorization': 'Bearer fake-key', 'X-MCP-Request': 'true'}
)
try:
    resp = urllib.request.urlopen(req)
    print(f'MCP call: HTTP {resp.status} (allowed)')
except urllib.error.HTTPError as e:
    print(f'MCP call: HTTP {e.code} (unexpected)')

```

```output
MCP call: HTTP 200 (allowed)
```

```python3

import urllib.request, json

# Direct agent call: API key only → BLOCKED
req = urllib.request.Request(
    'http://localhost:8000/api/v1/projects',
    headers={'Authorization': 'Bearer fake-key'}
)
try:
    urllib.request.urlopen(req)
except urllib.error.HTTPError as e:
    body = json.loads(e.read())
    print(f'Direct call: HTTP {e.code} — {body["detail"][:50]}')

```

```output
Direct call: HTTP 403 — Agents can only access /api/v1/agents/* routes. Us
```
