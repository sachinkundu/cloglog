# T-126: Fix agent task count — exclude done/archived

*2026-04-07T16:28:44Z by Showboat 0.6.1*
<!-- showboat-id: ae40dd39-e22a-4b3c-9044-ea079d743fc3 -->

Agent task counts in the sidebar now exclude done and archived tasks. Only backlog, in_progress, and review tasks are counted.

```bash
cd frontend && NO_COLOR=1 npx vitest run 2>&1 | grep -E '(Tests|Test Files|FAIL|passed|failed)'
```

```output
 Test Files  24 passed (24)
      Tests  193 passed (193)
```

One-line fix in App.tsx agentTaskCounts memo. No new tests needed — existing tests cover the count display.
