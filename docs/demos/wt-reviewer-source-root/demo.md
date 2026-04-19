# The PR reviewer now reads source files from a configured main checkout instead of Path.cwd(). False-negatives where codex couldn't see code already merged to main (because the backend runs out of a prod checkout that trails main) are eliminated.

*2026-04-19T15:15:17Z by Showboat 0.6.1*
<!-- showboat-id: bb0e9c64-7d2f-449c-b50c-7af0c07f6605 -->

Bug scenario (observed on PR #158): backend process runs out of /home/sachin/code/cloglog-prod/, which is a git worktree that only advances on `make promote`. The review engine passed `-C $(cwd)` to codex, so codex's filesystem view was the prod checkout. When a PR referenced code merged to main but not yet promoted, codex flagged it as missing. Reviewers learn to dismiss codex → genuine issues hide in the noise.

Fix: new Settings field `review_source_root: Path | None` (env REVIEW_SOURCE_ROOT). When set, the review engine passes that path to codex's `-C` flag and uses it as the subprocess cwd. Unset → falls back to Path.cwd() (fine for dev). Prod must export REVIEW_SOURCE_ROOT pointing at the main checkout.

Proof 1 — Settings carries the new field with the right type and default.

```bash
grep -c "review_source_root: Path | None" src/shared/config.py
```

```output
1
```

Proof 2 — review_engine._run_review_agent now resolves project_root via the setting, with Path.cwd() only as a fallback when unset.

```bash
grep -c "settings.review_source_root or Path.cwd()" src/gateway/review_engine.py
```

```output
2
```

Proof 3 — the buggy `project_root = Path.cwd()` assignment (no setting fallback) is gone. If a future refactor reintroduces it, this proof flips from 'fixed' to 'bug remains'.

```bash
if grep -qE "^        project_root = Path\.cwd\(\)$" src/gateway/review_engine.py; then echo "bug remains"; else echo "fixed"; fi
```

```output
fixed
```

Proof 4a — with REVIEW_SOURCE_ROOT unset, Settings.review_source_root is None and the engine falls back to Path.cwd().

```bash
env -u REVIEW_SOURCE_ROOT uv run --no-sync python -c "from src.shared.config import Settings; s = Settings(_env_file=None); print(\"review_source_root:\", s.review_source_root)"
```

```output
review_source_root: None
```

Proof 4b — with REVIEW_SOURCE_ROOT set, Settings picks it up as a Path and the engine will pass that value to codex -C.

```bash
REVIEW_SOURCE_ROOT=/home/sachin/code/cloglog uv run --no-sync python -c "from src.shared.config import Settings; s = Settings(_env_file=None); print(\"review_source_root:\", s.review_source_root)"
```

```output
review_source_root: /home/sachin/code/cloglog
```

Proof 5 — new helper `log_review_source_root` is wired into app.py's lifespan so the backend logs the resolved path and HEAD SHA at boot. A stale prod checkout becomes visible in the log, not just in false-negative reviews.

```bash
grep -l log_review_source_root src/gateway/app.py src/gateway/review_engine.py | wc -l
```

```output
2
```

Proof 6 — new TestReviewSourceRoot class covers both branches (setting set / None), the regression guard that -C is always passed, and the startup-log probe against a bogus path and a real git dir. 7 new tests, all pass; the full review-engine file still passes 71 tests end-to-end.

```bash
uv run pytest tests/gateway/test_review_engine.py -k TestReviewSourceRoot -q --no-header 2>&1 | grep -oE "[0-9]+ passed"
```

```output
7 passed
```

```bash
uv run pytest tests/gateway/test_review_engine.py -q --no-header 2>&1 | grep -oE "[0-9]+ passed"
```

```output
71 passed
```
