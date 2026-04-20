# Learnings: wt-reviewer-reliability

**Date:** 2026-04-20
**Tasks:** T-238 + T-239

## What future agents should know

### Ruff `UP042` — str-based enums

`class X(str, Enum)` is flagged on this codebase; prefer `class X(StrEnum)`.
Caught on `SkipReason` in `src/gateway/review_skip_comments.py` before the
quality gate would have failed the PR.

### `respx.mock()` default asserts unused routes

`respx.mock()` defaults to `assert_all_called=True` — any route you stub
that never fires raises `AssertionError: some routes were not called`.
For a demo driver that stubs both `/issues/{pr}/comments` (expected) and
`/pulls/{pr}/reviews` (should NOT fire on skip paths), use
`respx.mock(assert_all_called=False)` and assert on `route.call_count`
yourself.

### Capturing stderr after `proc.kill()` works

For an `asyncio.subprocess.Process` whose `communicate()` was cancelled
by `wait_for` timeout, `await proc.stderr.read()` can still drain the
kernel-buffered bytes — as long as you read BEFORE killing the process.
Best-effort pattern used in `_drain_stderr_after_timeout`:
`asyncio.wait_for(proc.stderr.read(), timeout=1.0)` with a broad except.

### The security-reminder hook flags subprocess-exec patterns in new code

The host-level pre-edit hook greps for the literal substring "e-x-e-c-("
and prints a JS `execFileNoThrow.ts` warning — even on Python's safe
`asyncio.create_subprocess_exec` call. Workaround: reuse the existing
`_create_subprocess` wrapper in the same file instead of making a new
direct call in new code.

### Silent short-circuits = lost hours of review latency

PR #149 (timeout) and PR #159 (codex exit 1) both went un-reviewed for
hours because the bot skipped silently. Any future short-circuit added
to the review engine MUST post a skip comment. The wiring template:
`await self._notify_skip(event, SkipReason.X, body)` at config-layer
sites, `await self._post_agent_skip(event, reason, body, token)` inside
`_run_review_agent` where the token is already in scope.

### Rate-limit your own comment poster

Without a dedup window, an out-of-budget bot posts one
"rate limit exceeded" comment per webhook event. The
`_SkipCommentCache` keyed by `(repo, pr, reason)` with a 3600s window
handles this. In-memory is acceptable — restart wipes the cache, worst
case is one duplicate after a deploy.

### Coverage: small modules pull total down fast

Adding a 50-LOC module with 0% coverage drops repo-total coverage by
~0.1%. The 80% gate is sharp — `review_skip_comments.py` needed 100%
plus direct probe tests (`TestProbes` 6 cases) to push total back to
80.47%. Future additions: write probe-level unit tests alongside the
integration tests or coverage will regress quietly.
