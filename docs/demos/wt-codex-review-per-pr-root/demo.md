# Codex now reviews the PR's owning worktree, not prod's stale main. T-278 resolves project_root per PR via an Agent Open Host Service; the old host-level fallback (T-255) remains for PRs whose worktree is not on this host.

*2026-04-23T14:16:19Z by Showboat 0.6.1*
<!-- showboat-id: fbdd1bdf-663e-47b1-ad21-6bcd58db82ca -->

### T-278 acceptance evidence — file-level booleans

Every T-278 acceptance item reduces to a file-level change (new helper,
new Protocol, new repository method, new OHS factory) or a regression
guard (DDD boundary pin). The exec blocks below prove each one as a
boolean without touching a live service — safe under `showboat verify`.

```bash
F=src/gateway/review_engine.py
   grep -q "^async def resolve_pr_review_root" "$F" && echo "resolve_pr_review_root_defined=yes" || echo "resolve_pr_review_root_defined=MISSING"
   grep -q "def resolve_review_source_root" "$F" && echo "host_level_resolver_preserved=yes" || echo "host_level_resolver_preserved=MISSING"
```

```output
resolve_pr_review_root_defined=yes
host_level_resolver_preserved=yes
```

```bash
F=src/agent/interfaces.py
   grep -q "class IWorktreeQuery" "$F" && echo "IWorktreeQuery_protocol_defined=yes" || echo "IWorktreeQuery_protocol_defined=MISSING"
   grep -q "class WorktreeRow" "$F" && echo "WorktreeRow_dto_defined=yes" || echo "WorktreeRow_dto_defined=MISSING"
   grep -q "async def find_by_branch" "$F" && echo "find_by_branch_protocol_method=yes" || echo "find_by_branch_protocol_method=MISSING"
```

```output
IWorktreeQuery_protocol_defined=yes
WorktreeRow_dto_defined=yes
find_by_branch_protocol_method=yes
```

```bash
F=src/agent/services.py
   grep -q "^def make_worktree_query" "$F" && echo "make_worktree_query_factory=yes" || echo "make_worktree_query_factory=MISSING"
```

```output
make_worktree_query_factory=yes
```

```bash
F=src/agent/repository.py
   grep -q "async def find_worktree_by_branch_any_status" "$F" && echo "repository_method=yes" || echo "repository_method=MISSING"
```

```output
repository_method=yes
```

```bash
F=src/gateway/review_engine.py
   grep -q "project_root = await resolve_pr_review_root" "$F" && echo "call_site_uses_per_pr_resolver=yes" || echo "call_site_uses_per_pr_resolver=MISSING"
```

```output
call_site_uses_per_pr_resolver=yes
```

### DDD boundary — Gateway must NOT import Agent models or repository

Per `docs/ddd-context-map.md` (Gateway owns no tables) and the PR #187
round 2 CRITICAL precedent, Gateway consumes Agent only through the
Protocol + factory. The two grep invocations below assert **absence**
(non-zero exit) — catching both top-level and lazy imports. CLAUDE.md
"Leak-after-fix" rule: asserting absence beats asserting presence.

```bash
F=src/gateway/review_engine.py
   if grep -qE "^from src\.agent\.(models|repository)" "$F"; then
     echo "top_level_agent_models_or_repository_import=PRESENT_FAIL"
   else
     echo "top_level_agent_models_or_repository_import=absent_ok"
   fi
   if grep -qE "from src\.agent\.(models|repository)" "$F"; then
     echo "any_indent_agent_models_or_repository_import=PRESENT_FAIL"
   else
     echo "any_indent_agent_models_or_repository_import=absent_ok"
   fi
```

```output
top_level_agent_models_or_repository_import=absent_ok
any_indent_agent_models_or_repository_import=absent_ok
```

### In-process behaviour proofs

`docs/demos/wt-codex-review-per-pr-root/proof.py` wires a stub
`IWorktreeQuery`, a synthetic `WebhookEvent`, and a tmp git repo (for
the drift case) to exercise `resolve_pr_review_root` without any DB,
webhook, or codex subprocess. Each mode prints only boolean OK/FAIL
lines — no SHAs, no timestamps — so `showboat verify` stays byte-exact.

```bash
uv run python docs/demos/wt-codex-review-per-pr-root/proof.py happy
```

```output
returns_worktree_path=True
no_fallback_warning=True
no_drift_warning=True
logged_worktree_source=True
```

```bash
uv run python docs/demos/wt-codex-review-per-pr-root/proof.py fallback
```

```output
returns_fallback_path=True
logged_no_matching_worktree=True
```

```bash
uv run python docs/demos/wt-codex-review-per-pr-root/proof.py drift
```

```output
returns_worktree_path=True
shas_differ=True
logged_drift_warning=True
```

### Spec updated

`docs/design/two-stage-pr-review.md` §9 documents the per-PR review-
root rule as authoritative; future readers find the answer in the spec,
not by spelunking git.

```bash
F=docs/design/two-stage-pr-review.md
   grep -q "## 9. Per-PR review root resolution" "$F" && echo "spec_section_9_present=yes" || echo "spec_section_9_present=MISSING"
   grep -q "T-278" "$F" && echo "spec_cites_T-278=yes" || echo "spec_cites_T-278=MISSING"
   grep -q "T-255" "$F" && echo "spec_cites_T-255=yes" || echo "spec_cites_T-255=MISSING"
```

```output
spec_section_9_present=yes
spec_cites_T-278=yes
spec_cites_T-255=yes
```
