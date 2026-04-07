# T-61: Agent management panel — view and remove worktrees

*2026-04-07T15:31:03Z by Showboat 0.6.1*
<!-- showboat-id: 2fe12f50-5bf8-47ac-b02c-d3c884026bca -->

New 'Manage Agents' panel in the sidebar. Click an agent to expand details (status, branch, heartbeat, task count). Online agents show a 'Request Shutdown' button that sets shutdown_requested on the worktree record.

```bash {image}
![Agent panel with expanded details and shutdown button](docs/demos/wt-ui/agent-panel.png)
```

![Agent panel with expanded details and shutdown button](ab7187dc-2026-04-07.png)

```bash
cd frontend && NO_COLOR=1 npx vitest run src/components/AgentPanel.test.tsx 2>&1 | grep -E '(Tests|Test Files|FAIL|passed|failed)'
```

```output
 Test Files  1 passed (1)
      Tests  8 passed (8)
```

Test delta: 183 -> 191 (+8 new). AgentPanel component tests, integration test fix for duplicate names.
