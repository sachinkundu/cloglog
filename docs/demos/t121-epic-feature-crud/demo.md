# Demo: T-121 — Update/delete MCP tools for epics and features

## New endpoints

### `PATCH /api/v1/epics/{epic_id}` — Update an epic

```bash
curl -X PATCH http://localhost:8000/api/v1/epics/abc-123 \
  -H "Content-Type: application/json" \
  -d '{"title": "Auth & SSO Epic", "description": "Authentication with SSO support"}'
```

```json
{
  "id": "abc-123",
  "project_id": "proj-1",
  "title": "Auth & SSO Epic",
  "description": "Authentication with SSO support",
  "bounded_context": "",
  "context_description": "",
  "status": "active",
  "position": 0,
  "color": "#6366f1",
  "number": 1,
  "created_at": "2026-04-08T11:00:00Z"
}
```

All fields are optional — only the ones you send are updated.

### `PATCH /api/v1/features/{feature_id}` — Update a feature

```bash
curl -X PATCH http://localhost:8000/api/v1/features/feat-1 \
  -H "Content-Type: application/json" \
  -d '{"title": "OAuth Login", "status": "done"}'
```

```json
{
  "id": "feat-1",
  "epic_id": "abc-123",
  "title": "OAuth Login",
  "description": "",
  "status": "done",
  "position": 0,
  "number": 1,
  "created_at": "2026-04-08T11:00:00Z"
}
```

### `DELETE /api/v1/epics/{epic_id}` — Delete an epic (already existed)

```bash
curl -X DELETE http://localhost:8000/api/v1/epics/abc-123
# 204 No Content
```

### `DELETE /api/v1/features/{feature_id}` — Delete a feature (already existed)

```bash
curl -X DELETE http://localhost:8000/api/v1/features/feat-1
# 204 No Content
```

### Error: 404 for unknown entities

```bash
curl -X PATCH http://localhost:8000/api/v1/epics/00000000-0000-0000-0000-000000000000 \
  -H "Content-Type: application/json" \
  -d '{"title": "nope"}'
```

```json
{"detail": "Epic not found"}
```

---

## New MCP tools

| Tool | Method | Endpoint | Parameters |
|------|--------|----------|------------|
| `update_epic` | PATCH | `/epics/{id}` | epic_id, title?, description?, bounded_context?, status? |
| `delete_epic` | DELETE | `/epics/{id}` | epic_id |
| `update_feature` | PATCH | `/features/{id}` | feature_id, title?, description?, status? |
| `delete_feature` | DELETE | `/features/{id}` | feature_id |

These complement the existing `update_task` / `delete_task` tools, giving full CRUD parity across all board entities.
