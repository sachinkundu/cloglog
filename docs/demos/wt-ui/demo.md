# T-51: Sort Incomplete Features Before Completed in Backlog Tree

*2026-04-07T11:56:12Z by Showboat 0.6.1*
<!-- showboat-id: 59e1da84-502d-4487-b060-e95db0255e5e -->

When 'Show completed' is toggled on, incomplete epics and features now sort before completed ones. Two new component tests verify the DOM ordering.

```bash
cd /home/sachin/code/cloglog/.claude/worktrees/wt-ui/frontend && NO_COLOR=1 npx vitest run src/components/BacklogTree.test.tsx 2>&1 | grep -E '(Tests|FAIL|passed|failed)'
```

```output
 Test Files  1 passed (1)
      Tests  14 passed (14)
```

Test delta: 174 -> 176 tests (+2 new sorting tests). 0 modified.
