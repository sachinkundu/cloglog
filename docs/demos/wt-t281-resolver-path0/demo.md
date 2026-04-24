# Codex now reviews main-agent close-out PRs against the PR's actual commit — no more false-positive findings from reading prod's stale main tree.

*2026-04-24T07:15:16Z by Showboat 0.6.1*
<!-- showboat-id: eb4f3386-cbd0-440c-8d0b-4a1500f7dc44 -->

### Scope evidence — file-level booleans

Every T-281 scope item maps to a named symbol added in a specific file.
The booleans below prove each one landed where the task description
said it would.

```bash
I=src/agent/interfaces.py
   grep -q "async def find_by_pr_url" "$I" && echo "interfaces_find_by_pr_url=yes" || echo "interfaces_find_by_pr_url=MISSING"
   grep -q "WorktreeRow | None" "$I" && echo "interfaces_returns_worktreerow=yes" || echo "interfaces_returns_worktreerow=MISSING"
```

```output
interfaces_find_by_pr_url=yes
interfaces_returns_worktreerow=yes
```

```bash
S=src/agent/services.py
   grep -q "async def find_by_pr_url" "$S" && echo "services_find_by_pr_url=yes" || echo "services_find_by_pr_url=MISSING"
   grep -q "find_task_by_pr_url_for_project" "$S" && echo "services_uses_project_scoped_join=yes" || echo "services_uses_project_scoped_join=MISSING"
   grep -q "BoardRepository(session)" "$S" && echo "factory_wires_board_repo=yes" || echo "factory_wires_board_repo=MISSING"
```

```output
services_find_by_pr_url=yes
services_uses_project_scoped_join=yes
factory_wires_board_repo=yes
```

```bash
R=src/gateway/review_engine.py
   grep -q "class PrReviewRoot" "$R" && echo "dataclass_defined=yes" || echo "dataclass_defined=MISSING"
   grep -q "is_temp: bool = False" "$R" && echo "is_temp_field=yes" || echo "is_temp_field=MISSING"
   grep -q "main_clone: Path | None" "$R" && echo "main_clone_field=yes" || echo "main_clone_field=MISSING"
```

```output
dataclass_defined=yes
is_temp_field=yes
main_clone_field=yes
```

```bash
R=src/gateway/review_engine.py
   grep -q "async def _create_review_checkout" "$R" && echo "create_helper=yes" || echo "create_helper=MISSING"
   grep -q "async def _remove_review_checkout" "$R" && echo "remove_helper=yes" || echo "remove_helper=MISSING"
   grep -q "review-checkouts" "$R" && echo "temp_dir_path_anchor=yes" || echo "temp_dir_path_anchor=MISSING"
```

```output
create_helper=yes
remove_helper=yes
temp_dir_path_anchor=yes
```

```bash
R=src/gateway/review_engine.py
   grep -q "review_root = await resolve_pr_review_root" "$R" && echo "caller_uses_pr_review_root=yes" || echo "caller_uses_pr_review_root=MISSING"
   grep -q "if review_root.is_temp and review_root.main_clone is not None" "$R" && echo "caller_finally_cleanup=yes" || echo "caller_finally_cleanup=MISSING"
```

```output
caller_uses_pr_review_root=yes
caller_finally_cleanup=yes
```

```bash
R=src/gateway/review_engine.py
   grep -q "from src.agent.models" "$R" && echo "ddd_violation_models=LEAK" || echo "ddd_violation_models=none"
   grep -q "from src.agent.repository" "$R" && echo "ddd_violation_repository=LEAK" || echo "ddd_violation_repository=none"
   grep -c "make_worktree_query" "$R"
```

```output
ddd_violation_models=none
ddd_violation_repository=none
3
```

```bash
D=docs/design/two-stage-pr-review.md
   grep -q "T-281" "$D" && echo "spec_references_t281=yes" || echo "spec_references_t281=MISSING"
   grep -q "Path 0" "$D" && echo "spec_mentions_path_0=yes" || echo "spec_mentions_path_0=MISSING"
   grep -q "SHA-check + temp-dir" "$D" && echo "spec_mentions_sha_check=yes" || echo "spec_mentions_sha_check=MISSING"
```

```output
spec_references_t281=yes
spec_mentions_path_0=yes
spec_mentions_sha_check=yes
```

### Behaviour proof — in-process resolver runs

Three standalone Python proofs exercise the real resolver + `_review_pr`
code paths with stubbed worktree queries and mocked git helpers.  No
pytest, no DB — `python3 proof_*.py` runs them directly.  The three
printed key=value blocks below are the exact bytes `showboat verify`
re-compares against.

```bash
uv run python docs/demos/wt-t281-resolver-path0/proof_path0.py
```

```output
path_0_hits_for_close_out_pr=yes
is_temp=no
path_matches_main_clone=yes
```

```bash
uv run python docs/demos/wt-t281-resolver-path0/proof_sha_mismatch.py
```

```output
sha_mismatch_triggers_temp_dir=yes
is_temp=yes
create_called_with_event_head_sha=yes
cleanup_anchor_set=yes
```

```bash
uv run python docs/demos/wt-t281-resolver-path0/proof_cleanup.py
```

```output
reviewer_raised=yes
remove_called_once=yes
remove_called_with_main_clone=yes
remove_called_with_temp_path=yes
```
