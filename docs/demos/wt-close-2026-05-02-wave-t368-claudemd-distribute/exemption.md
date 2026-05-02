---
diff_hash: 7f6f1d7e727a758006df5e1d677fa1c02f755ca59c5c084914d45e770731aa8e
classifier: human-operator
reason: docs-only-close-wave-+-plugin-mirror-sync
---

# Demo exemption — close-wave + plugin doc mirror sync

This branch ships:

1. `docs/work-logs/2026-05-02-wave-t368-claudemd-distribute-work-log.md` — the archived T-368 worktree work log (close-wave artifact preservation).
2. `plugins/cloglog/docs/agent-lifecycle.md` — sync the plugin mirror's §5.5 prose to match the authoritative `docs/design/agent-lifecycle.md` updated in PR #284. Codex review on #285 flagged the drift.

Both changes are documentation. No runtime code, no user-observable surface change. Plugin mirror lives at `plugins/cloglog/docs/` which is not in the demo allowlist regex (which currently covers `plugins/*/{hooks,skills,agents,templates}/` only — extending it to include `docs` is a separate concern requiring a parallel update to `tests/test_check_demo_allowlist.py::DEMO_ALLOWLIST_REGEX` and a new path in `ALLOWLISTED_PATHS`).
