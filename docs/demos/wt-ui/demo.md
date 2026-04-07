# T-112: Show agent worktree name on task cards

*2026-04-07T12:03:15Z by Showboat 0.6.1*
<!-- showboat-id: 21a0a4ec-73b9-4abe-b5a1-84f7a0a79a8a -->

Task cards and detail panel now show the worktree name (e.g. wt-backend) instead of generic 'agent assigned'. Falls back to 'agent assigned' if the worktree lookup fails.

```bash
cd frontend && NO_COLOR=1 npx vitest run src/components/TaskCard.test.tsx 2>&1 | grep -E '(Tests|FAIL|passed|failed)'
```

```output
 Test Files  1 passed (1)
      Tests  13 passed (13)
```

Test delta: 176 -> 178 tests (+2 new). Tests worktree name display and fallback.
