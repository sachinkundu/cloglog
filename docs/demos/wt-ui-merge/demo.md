# T-152: PR Merge Status Badge

*2026-04-10T11:32:46Z by Showboat 0.6.1*
<!-- showboat-id: 20b6c998-d677-43f7-9b3a-bfdfb242d222 -->

Task cards show a green Merged badge next to PR links when pr_merged is true.

PrLink component renders Merged badge when merged prop is true:

```bash
grep -A1 "merged" /home/sachin/code/cloglog/.claude/worktrees/wt-ui-merge/frontend/src/components/PrLink.tsx | head -4
```

```output
  merged?: boolean
}
--
export function PrLink({ url, merged }: PrLinkProps) {
```

```bash
grep "merged" /home/sachin/code/cloglog/.claude/worktrees/wt-ui-merge/frontend/src/components/PrLink.tsx
```

```output
  merged?: boolean
export function PrLink({ url, merged }: PrLinkProps) {
      {merged && <span className="pr-merged-badge">Merged</span>}
```

TaskCard passes pr_merged to PrLink:

```bash
grep "PrLink" /home/sachin/code/cloglog/.claude/worktrees/wt-ui-merge/frontend/src/components/TaskCard.tsx
```

```output
import { PrLink } from './PrLink'
        {task.pr_url && <PrLink url={task.pr_url} merged={task.pr_merged} />}
```

CardDetail also shows the merged badge:

```bash
grep "PrLink" /home/sachin/code/cloglog/.claude/worktrees/wt-ui-merge/frontend/src/components/CardDetail.tsx
```

```output
import { PrLink } from './PrLink'
            {task.pr_url && <PrLink url={task.pr_url} merged={task.pr_merged} />}
```

pr_merged added to OpenAPI contract:

```bash
grep -B1 -A2 "pr_merged" /home/sachin/code/cloglog/.claude/worktrees/wt-ui-merge/docs/contracts/baseline.openapi.yaml
```

```output
          title: Pr Url
        pr_merged:
          type: boolean
          title: Pr Merged
```

Generated TypeScript type includes pr_merged:

```bash
grep -B1 -A1 "pr_merged" /home/sachin/code/cloglog/.claude/worktrees/wt-ui-merge/frontend/src/api/generated-types.ts
```

```output
             */
            pr_merged: boolean;
        };
```
