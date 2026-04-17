# F-36 Review Engine — Manual E2E Recipe

The F-36 review engine is driven by GitHub webhooks against a local Codex CLI
subprocess. There is no automated end-to-end test in CI because the flow
requires:

- A live cloudflared tunnel exposing `cloglog.voxdez.com`.
- A configured GitHub App webhook pointing at that tunnel.
- A working `codex` binary on `PATH`.
- A scratch branch and a real pull request.

The unit + integration suite (`tests/gateway/test_review_engine.py`) exercises
every code path with subprocess and GitHub both mocked; this recipe is what
you run by hand before a release or when changing the prompt template or the
CLI invocation.

## Pre-flight

1. Confirm tunnel is up and GitHub App webhook points at the tunnel.
   ```bash
   sudo systemctl status cloudflared
   curl -s https://cloglog.voxdez.com/health
   # expect: {"status":"ok"}
   ```
2. Confirm the review agent is on PATH and `settings.review_enabled=true`.
   ```bash
   which "$(uv run python -c 'from src.shared.config import settings; print(settings.review_agent_cmd)')"
   ```
3. Confirm the PEM private key is present at `~/.agent-vm/credentials/github-app.pem`.
4. Start the backend (picks up `review_enabled` and registers the consumer).
   The startup log should contain either:
   - `ReviewEngineConsumer registered (agent=codex)` — consumer is live, OR
   - `Review agent 'codex' not on PATH — ReviewEngineConsumer disabled` —
     install or re-point `REVIEW_AGENT_CMD` before continuing.

## Trigger path

1. Create a throwaway branch with a small but non-trivial change.
   ```bash
   git checkout -b wt-review-engine-e2e-smoke
   echo "# smoke test" >> README.md
   git commit -am "smoke: review engine e2e"
   ```
2. Push and open a PR **as a human, not as the bot** — the self-review guard
   skips PRs authored by `cloglog-agent[bot]`.
   ```bash
   git push -u origin wt-review-engine-e2e-smoke
   gh pr create --title "smoke: review engine" --body "E2E smoke test, ignore"
   ```
3. Tail the backend log. You should see, in order:
   - A webhook delivery (`POST /api/v1/webhooks/github`) with
     `X-GitHub-Event: pull_request` and `action: opened`.
   - The consumer entering its lock and launching the agent.
   - `Review posted for PR #<N>: verdict=... findings=...`
4. Verify on GitHub:
   - The PR now has a review from `cloglog-agent[bot]` under
     `https://github.com/<owner>/<repo>/pull/<N>/reviews`.
   - If the review posted with `REQUEST_CHANGES`, the PR status widget
     reflects that; inline comments (if any) appear on the commented lines.

## Failure modes to verify

Each of these has a unit test; reproduce them by hand when you touch the
relevant code path.

| Scenario | How to reproduce | Expected log |
|---|---|---|
| Diff too large | Push a commit that adds >200K chars of code | `diff (<N> chars) exceeds 200000-char cap — skipping review` |
| Agent not on PATH | Run backend with `REVIEW_AGENT_CMD=definitely-not-a-real-binary` | At startup: `Review agent '...' not on PATH — ReviewEngineConsumer disabled` |
| Agent timeout | Replace the agent with `sleep 1000`, open a PR | `Review agent timed out for PR #<N>` |
| Agent writes malformed JSON | Replace the agent with a script that writes `"oops"` to the promised `review.json` | `Review agent output unparseable: ...` |
| Rate limit | Open 11 PRs in quick succession (or set `REVIEW_MAX_PER_HOUR=0`) | `Review rate limit exceeded, skipping PR #<N>` |
| Self-review guard | Bot opens a PR via the `github-bot` skill | No review posted; no agent launched |
| GitHub API 5xx on post | Block `api.github.com` at the network layer | First attempt + retry + `post_review failed for PR #<N> after retry: ... — dropping review` |

## Cleanup

```bash
gh pr close <N> --delete-branch
```

## When to re-run this

- Prompt template change in `review_engine.py`.
- Codex CLI invocation change (`--prompt`, `--approval-mode`, etc.).
- Any change to the webhook payload parsing or the consumer's gating logic.
- GitHub API version bump (`X-GitHub-Api-Version`).
