# T-112: Show agent worktree name on task cards

*2026-04-07T13:52:31Z by Showboat 0.6.1*
<!-- showboat-id: 389df86e-ca4f-4fc1-838d-cd055b6d6dae -->

Task cards and the detail panel now show the worktree name (e.g. 'wt-ui') instead of generic 'agent assigned'. Falls back to 'agent assigned' when the worktree is not in the lookup map.

```bash {image}
![In Progress column showing wt-ui on task cards](docs/demos/wt-ui/in-progress-col.png)
```

![In Progress column showing wt-ui on task cards](d233ee62-2026-04-07.png)

```bash
cd frontend && NO_COLOR=1 npx vitest run src/components/TaskCard.test.tsx 2>&1 | grep -E '(Tests|Test Files|FAIL|passed|failed)'
```

```output
 Test Files  1 passed (1)
      Tests  13 passed (13)
```

Test delta: 176 -> 178 (+2 new). Tests worktree name display and fallback to 'agent assigned'.
