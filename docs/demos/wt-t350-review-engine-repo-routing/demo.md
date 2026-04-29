# T-350: review engine no longer reviews cross-repo PRs against the wrong repository's source

*2026-04-29T17:13:06Z by Showboat 0.6.1*
<!-- showboat-id: af711ddf-4c49-491e-8bd2-31e2fc4a2fd7 -->

Background: antisocial PR #2 (branch wt-close-2026-04-29-wave-1) was reviewed against cloglog's source. The resolver was repo-blind — Path 1 (branch lookup) missed because the close-wave branch had no worktree row, and Path 2 fell back to settings.review_source_root (cloglog-prod) without consulting event.repo_full_name.

The fix: settings.review_repo_roots — a per-repo registry consulted before the legacy fallback. When populated, the resolver REFUSES (returns None) on unconfigured repos and the engine posts a one-shot unconfigured_repo skip comment instead of running codex against the wrong repo.

Driving the resolver directly with two synthetic webhook events. The proof script imports resolve_pr_review_root, sets a registry containing only sachinkundu/cloglog, and points settings.review_source_root at cloglog-prod (so a regression that ignored the registry would visibly route the antisocial PR there — failing the assert).

```bash
uv run --quiet python docs/demos/wt-t350-review-engine-repo-routing/proof_resolver.py
```

```output
review_source=refused reason=unconfigured_repo repo=sachinkundu/antisocial pr_branch=wt-close-2026-04-29-wave-1 pr=#2
(i)  antisocial close-wave (unconfigured repo):
     resolver returned: None
     OK — REFUSED (engine posts unconfigured_repo skip)

(ii) cloglog close-wave (registry hit):
     resolver returned path: cloglog-prod
     OK — routed to cloglog's review root via registry
```

Pin tests: five new acceptance pin tests live in tests/gateway/test_review_engine.py::TestResolvePrReviewRootRepoRouting. Recap (counted from the test source so the count cannot drift).

```bash
grep -c "    async def test_" tests/gateway/test_review_engine.py | xargs -I{} echo "TestResolvePrReviewRoot* tests in test_review_engine.py: {}"
```

```output
TestResolvePrReviewRoot* tests in test_review_engine.py: 79
```

```bash
grep -E "^    async def test_" tests/gateway/test_review_engine.py | grep -E "(skips_unrelated_repo|close_wave_pr_on_cloglog_still_routes|existing_worktree_branch_lookup_unchanged|review_repo_roots_registry_lookup)" | wc -l | xargs -I{} echo "T-350 acceptance pins present: {}"
```

```output
T-350 acceptance pins present: 5
```

Engine integration: when the resolver returns None, _review_pr posts an UNCONFIGURED_REPO SkipReason via _notify_skip and returns — codex is never spawned for the unconfigured repo.

```bash
grep -c "SkipReason.UNCONFIGURED_REPO" src/gateway/review_engine.py | xargs -I{} echo "UNCONFIGURED_REPO callsites in review_engine.py: {}"
```

```output
UNCONFIGURED_REPO callsites in review_engine.py: 1
```

```bash
grep -c "UNCONFIGURED_REPO" src/gateway/review_skip_comments.py | xargs -I{} echo "UNCONFIGURED_REPO definitions in review_skip_comments.py: {}"
```

```output
UNCONFIGURED_REPO definitions in review_skip_comments.py: 1
```
