# Agents no longer receive false ci_failed notifications when GitHub fires check_run events with a null (pending) conclusion.

*2026-04-18T17:24:39Z by Showboat 0.6.1*
<!-- showboat-id: 5972cdf4-16af-4b4e-85cf-24019a36c377 -->

Setup: the bug lived in AgentNotifierConsumer._build_message. The probe script drives that method directly with representative GitHub check_run payloads and prints the would-be inbox message (or 'None' when the event is silently ignored).

Before the fix: a check_run with conclusion:null produced a ci_failed message. GitHub fires this event every time a check is queued, so every agent got a false CI_FAILED page on every PR push.

After the fix: only GitHub's terminal non-success conclusions {failure, cancelled, timed_out, action_required, stale} produce a ci_failed notification. Everything else (null, success, neutral, skipped) is silently ignored.

Case 1 — conclusion: null (the bug scenario). Expect: None.

```bash
uv run python docs/demos/wt-t198-ci-failed-filter/probe.py null
```

```output
None  # no agent inbox message — event silently ignored
```

Case 2 — conclusion: success. Expect: None.

```bash
uv run python docs/demos/wt-t198-ci-failed-filter/probe.py success
```

```output
None  # no agent inbox message — event silently ignored
```

Case 3 — conclusion: neutral (terminal, not a failure). Expect: None.

```bash
uv run python docs/demos/wt-t198-ci-failed-filter/probe.py neutral
```

```output
None  # no agent inbox message — event silently ignored
```

Case 4 — conclusion: skipped (terminal, not a failure). Expect: None.

```bash
uv run python docs/demos/wt-t198-ci-failed-filter/probe.py skipped
```

```output
None  # no agent inbox message — event silently ignored
```

Case 5 — conclusion: failure. Expect: ci_failed message for the agent.

```bash
uv run python docs/demos/wt-t198-ci-failed-filter/probe.py failure
```

```output
{
  "type": "ci_failed",
  "pr_url": "https://github.com/sachinkundu/cloglog/pull/198",
  "pr_number": 198,
  "check_name": "quality",
  "conclusion": "failure",
  "message": "CI check 'quality' failure on PR #198. Use the github-bot skill to read the failed logs and push a fix."
}
```

Case 6 — conclusion: timed_out (another terminal failure). Expect: ci_failed message.

```bash
uv run python docs/demos/wt-t198-ci-failed-filter/probe.py timed_out
```

```output
{
  "type": "ci_failed",
  "pr_url": "https://github.com/sachinkundu/cloglog/pull/198",
  "pr_number": 198,
  "check_name": "quality",
  "conclusion": "timed_out",
  "message": "CI check 'quality' timed_out on PR #198. Use the github-bot skill to read the failed logs and push a fix."
}
```

Case 7 — conclusion: cancelled (terminal failure). Expect: ci_failed message.

```bash
uv run python docs/demos/wt-t198-ci-failed-filter/probe.py cancelled
```

```output
{
  "type": "ci_failed",
  "pr_url": "https://github.com/sachinkundu/cloglog/pull/198",
  "pr_number": 198,
  "check_name": "quality",
  "conclusion": "cancelled",
  "message": "CI check 'quality' cancelled on PR #198. Use the github-bot skill to read the failed logs and push a fix."
}
```
