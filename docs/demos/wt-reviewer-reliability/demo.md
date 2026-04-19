# PR authors and human reviewers now see a PR comment every time the Codex bot declines to review — no more silent skips like PR #149 (timeout) or PR #159 (exit 1).

*2026-04-19T15:55:44Z by Showboat 0.6.1*
<!-- showboat-id: fe549019-1806-4b0e-a4c1-4dbc96bfa9a4 -->

Wiring: each short-circuit site now calls the skip-comment helper.

```bash
grep -cE "_notify_skip\(|_post_agent_skip\(" src/gateway/review_engine.py
```

```output
8
```

Every SkipReason value is used at its corresponding site.

```bash
grep -oE "SkipReason\.[A-Z_]+" src/gateway/review_engine.py | sort -u
```

```output
SkipReason.AGENT_TIMEOUT
SkipReason.AGENT_UNPARSEABLE
SkipReason.DIFF_TOO_LARGE
SkipReason.MAX_REVIEWS
SkipReason.NO_REVIEWABLE_FILES
SkipReason.RATE_LIMIT
```

New tests — skip comments, retry/probe, happy-path regression guard.

```bash
uv run pytest tests/gateway/test_review_engine.py -q 2>/dev/null | grep -oE "[0-9]+ passed"
```

```output
97 passed
```

Live dispatch: each skip path fires exactly one comment POST.

```bash
uv run python docs/demos/wt-reviewer-reliability/drive_skip_reasons.py
```

```output
Review rate limit exceeded, skipping PR #101 (demo/repo)
PR #104 diff (400287 chars) exceeds 200000-char cap — skipping review
Review agent exited 1 for PR #105: demo unparseable stderr
Review agent produced no parseable output for PR #105
review_timeout {'event': 'review_timeout', 'pr_number': 106, 'attempt': 2, 'stderr_excerpt': 'demo timeout stderr', 'codex_alive': True, 'codex_probe': 'codex 1.0.0', 'github_reachable': True, 'github_probe': '200 zen', 'elapsed_seconds': 0.01}
rate_limit               pr=#101  comments_posted=1  OK
max_reviews              pr=#102  comments_posted=1  OK
no_reviewable_files      pr=#103  comments_posted=1  OK
diff_too_large           pr=#104  comments_posted=1  OK
agent_unparseable        pr=#105  comments_posted=1  OK
agent_timeout            pr=#106  comments_posted=1  OK
ALL OK
```

Timeout log entry schema (fields the F-49 supervisor will pattern-match).

```bash
grep -oE "\"(event|pr_number|attempt|stderr_excerpt|codex_alive|github_reachable|elapsed_seconds)\":" src/gateway/review_engine.py | sort -u
```

```output
"attempt":
"codex_alive":
"elapsed_seconds":
"event":
"github_reachable":
"pr_number":
"stderr_excerpt":
```
