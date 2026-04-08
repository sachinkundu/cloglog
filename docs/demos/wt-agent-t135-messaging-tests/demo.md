# T-135: Agent Messaging Tests & Cleanup

*2026-04-08T10:14:30Z by Showboat 0.6.1*
<!-- showboat-id: 9a049476-2789-4722-9c55-18555dc392fb -->

Added 13 tests for F-32 agent messaging. Fixed 3 broken complete_task tests. Removed prototype test_notification tool.

```bash
uv run pytest tests/agent/ -q 2>&1 | grep -oP "^\d+ passed"
```

```output
52 passed
```

```bash
cd mcp-server && npx vitest run --reporter=verbose 2>&1 | grep -c "✓"
```

```output
24
```

```bash
grep -c test_notification mcp-server/src/server.ts; true
```

```output
0
```
