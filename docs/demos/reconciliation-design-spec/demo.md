# Reconciliation Design Spec

*2026-04-06T10:14:03Z by Showboat 0.6.1*
<!-- showboat-id: 2aed8feb-13df-4bb4-92b7-687003822c52 -->

This is a design spec PR. The code change is check-demo.sh which skips demos for docs-only branches. Verify it works:

```bash
echo 'scripts/check-demo.sh' | grep -vE '^docs/|^CLAUDE\.md|^\.claude/' | head -1 && echo 'Has code changes — demo required (correct)'
```

```output
scripts/check-demo.sh
Has code changes — demo required (correct)
```

```bash
echo 'docs/specs/foo.md' | grep -vE '^docs/|^CLAUDE\.md|^\.claude/' | head -1 || echo 'Docs only — no demo required (correct)'
```

```output
```
