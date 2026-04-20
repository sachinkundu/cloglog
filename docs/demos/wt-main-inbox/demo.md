# Webhook events for close-wave PRs (wt-close-*) now reach the main agent's inbox instead of being silently dropped — the main agent finally sees its own PRs merge.

*2026-04-20T09:32:50Z by Showboat 0.6.1*
<!-- showboat-id: 5c488076-e15e-473c-8ca1-f28a1a35bd8e -->

The main-agent inbox path is opt-in via Settings — unset by default so the pre-T-253 drop behavior is preserved for projects that don't want it.

```bash
grep -c "main_agent_inbox_path: Path | None" src/shared/config.py
```

```output
1
```

The resolver now returns a self-documenting ResolvedRecipient dataclass (worktree_id=None signals the main-agent fallback). MAIN_AGENT_EVENTS is a frozenset that excludes ISSUE_COMMENT — bot comments would otherwise flood the main inbox.

```bash
grep -c "^class ResolvedRecipient:" src/gateway/webhook_consumers.py
```

```output
1
```

```bash
grep -c "ISSUE_COMMENT" src/gateway/webhook_consumers.py
```

```output
4
```

The fallback guard requires BOTH the config path AND a whitelisted event type — without either, the resolver falls through to the existing None return (drop).

```bash
grep -A1 "main_agent_inbox_path is not None and event.type in MAIN_AGENT_EVENTS" src/gateway/webhook_consumers.py | head -2
```

```output
        if settings.main_agent_inbox_path is not None and event.type in MAIN_AGENT_EVENTS:
            return ResolvedRecipient(inbox_path=settings.main_agent_inbox_path, worktree_id=None)
```

With MAIN_AGENT_INBOX_PATH unset, Settings loads main_agent_inbox_path as None — the third fallback is disabled and behavior matches the pre-T-253 baseline.

```bash
env -u MAIN_AGENT_INBOX_PATH uv run --no-sync python -c "from src.shared.config import Settings; s = Settings(_env_file=None); print(\"main_agent_inbox_path:\", s.main_agent_inbox_path)"
```

```output
main_agent_inbox_path: None
```

With MAIN_AGENT_INBOX_PATH set, Settings picks it up as a Path — operators opt in by adding this one line to their .env (or setting it in their deployment environment).

```bash
MAIN_AGENT_INBOX_PATH=/home/sachin/code/cloglog/.cloglog/inbox uv run --no-sync python -c "from src.shared.config import Settings; s = Settings(_env_file=None); print(\"main_agent_inbox_path:\", s.main_agent_inbox_path)"
```

```output
main_agent_inbox_path: /home/sachin/code/cloglog/.cloglog/inbox
```

Five new T-253 integration tests cover both paths of the fallback: on + off, the regression guard (worktree routing still wins when it matches), and the ISSUE_COMMENT filter.

```bash
uv run pytest tests/gateway/test_webhook_consumers.py::TestMainAgentFallback -q --no-header 2>&1 | grep -oE "[0-9]+ passed"
```

```output
5 passed
```

The full webhook-consumers test file still passes end-to-end, including the five new tests and the pre-existing resolver/message/inbox coverage.

```bash
uv run pytest tests/gateway/test_webhook_consumers.py -q --no-header 2>&1 | grep -oE "[0-9]+ passed"
```

```output
46 passed
```
