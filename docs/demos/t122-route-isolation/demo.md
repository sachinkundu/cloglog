# T-122: Server-side Route Isolation

*2026-04-06T09:53:19Z by Showboat 0.6.1*
<!-- showboat-id: 353b2691-a279-40bd-be7f-794195ac452f -->

Demonstrate that agents (requests with API key) are blocked from non-agent routes, while the frontend UI (no API key) passes through.

First, verify the server is running:

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

```output
{
    "status": "ok"
}
```

Agent request (with API key) to a board route — should be BLOCKED with 403:

```python3

import urllib.request, json
req = urllib.request.Request(
    'http://localhost:8000/api/v1/projects',
    headers={'Authorization': 'Bearer fake-agent-key'}
)
try:
    urllib.request.urlopen(req)
except urllib.error.HTTPError as e:
    body = json.loads(e.read())
    print(f'HTTP {e.code}: {body["detail"]}')

```

```output
HTTP 403: Agents can only access /api/v1/agents/* routes. Use MCP tools for all board operations.
```

Agent request to PATCH a task directly — also BLOCKED:

```python3

import urllib.request, json
data = json.dumps({'status': 'done'}).encode()
req = urllib.request.Request(
    'http://localhost:8000/api/v1/tasks/00000000-0000-0000-0000-000000000000',
    data=data,
    headers={'Authorization': 'Bearer fake-agent-key', 'Content-Type': 'application/json'},
    method='PATCH'
)
try:
    urllib.request.urlopen(req)
except urllib.error.HTTPError as e:
    body = json.loads(e.read())
    print(f'HTTP {e.code}: {body["detail"]}')

```

```output
HTTP 403: Agents can only access /api/v1/agents/* routes. Use MCP tools for all board operations.
```

Frontend UI request (no API key) to the same route — ALLOWED:

```python3

import urllib.request, json
req = urllib.request.Request('http://localhost:8000/api/v1/projects')
resp = urllib.request.urlopen(req)
data = json.loads(resp.read())
print(f'HTTP {resp.status}: returned {len(data)} projects')

```

```output
HTTP 200: returned 2 projects
```

Agent request to /agents/* route — ALLOWED (gets 401 for invalid key, not 403):

```python3

import urllib.request, json
data = json.dumps({'worktree_path': '/tmp/test'}).encode()
req = urllib.request.Request(
    'http://localhost:8000/api/v1/agents/register',
    data=data,
    headers={'Authorization': 'Bearer fake-agent-key', 'Content-Type': 'application/json'},
    method='POST'
)
try:
    urllib.request.urlopen(req)
except urllib.error.HTTPError as e:
    body = json.loads(e.read())
    print(f'HTTP {e.code}: {body["detail"]}')
    print('(401 = invalid key, but NOT 403 = route allowed)')

```

```output
HTTP 401: Invalid API key
(401 = invalid key, but NOT 403 = route allowed)
```
