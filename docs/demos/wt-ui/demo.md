# T-60: Agent click filters board, hover shows task count

*2026-04-07T12:08:57Z by Showboat 0.6.1*
<!-- showboat-id: cbe6a15c-24fb-4e7e-94a8-1f882948d4a8 -->

Clicking an agent in the sidebar filters all board columns to show only that agent's tasks. Click again to clear filter. Each agent shows its task count. Active filter is visually highlighted.

```bash
cd frontend && NO_COLOR=1 npx vitest run src/components/Sidebar.test.tsx src/components/Column.test.tsx 2>&1 | grep -E '(Tests|Test Files|FAIL|passed|failed)'
```

```output
 Test Files  2 passed (2)
      Tests  33 passed (33)
```

Test delta: 178 -> 183 tests (+5 new). Agent click, filter highlight, task count display, column agent filtering.
