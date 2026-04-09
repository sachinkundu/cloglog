# T-117 Auto-Attach Documents + T-152 PR Merge Status

*2026-04-09T08:32:57Z by Showboat 0.6.1*
<!-- showboat-id: 9b37279e-7edc-47ad-940d-a3a461ad695c -->

## T-117: Auto-attach document when spec/plan task moves to review

Create entities, move spec to review with a PR URL, verify Document auto-created.

```bash
bash /tmp/demo-t117.sh
```

```output
=== 1. Created spec task (pr_merged defaults to false) ===
{
  "title": "Write design spec",
  "task_type": "spec",
  "status": "backlog",
  "pr_url": null,
  "pr_merged": false
}

=== 2. Move to in_progress ===
{
  "status": "in_progress",
  "pr_url": null
}

=== 3. Move to review with pr_url — triggers auto-attach ===
{
  "status": "review",
  "pr_url": "https://github.com/org/repo/pull/42"
}

=== 4. Query documents for the feature — document was auto-created ===
{
  "title": "Spec — Write design spec",
  "doc_type": "design_spec",
  "source_path": "https://github.com/org/repo/pull/42",
  "attached_to_type": "feature"
}

=== 5. Dedup: move back to review with same URL — no duplicate ===
Document count after re-review: 1 (no duplicate)
```

## T-152: PR merge status field

New `pr_merged` boolean on Task. Set it via PATCH, verify it shows on board and active-tasks.

```bash
bash /tmp/demo-t152.sh
```

```output
=== 1. New task has pr_merged: false by default ===
{
  "title": "Implement login",
  "pr_url": null,
  "pr_merged": false
}

=== 2. Set pr_url and pr_merged via PATCH ===
{
  "title": "Implement login",
  "pr_url": "https://github.com/org/repo/pull/50",
  "pr_merged": true
}

=== 3. Board endpoint shows pr_merged in task cards ===
{
  "title": "Implement login",
  "pr_url": "https://github.com/org/repo/pull/50",
  "pr_merged": true
}

=== 4. Active-tasks endpoint includes pr_merged ===
{
  "title": "Implement login",
  "pr_url": "https://github.com/org/repo/pull/50",
  "pr_merged": true
}
```
