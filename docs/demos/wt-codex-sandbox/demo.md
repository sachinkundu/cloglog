# PR reviews now run codex without bwrap, fixing the RTM_NEWADDR failure that made every review on PR #152 fall back to a 'sandbox error' message instead of real analysis.

*2026-04-19T11:29:16Z by Showboat 0.6.1*
<!-- showboat-id: 72bcce40-786d-4bab-8042-46f961634ca0 -->

Evidence 1 — This is the actual review the cloglog-codex-reviewer bot posted on PR #152 earlier today. The failure mode is public and reproducible: whenever codex's shell-tool fires, bwrap's unshare-net dies with RTM_NEWADDR because this host lacks CAP_NET_ADMIN. Without the fix, every review produces this fallback message instead of findings.

```bash
gh api repos/sachinkundu/cloglog/pulls/152/reviews --jq ".[0].body" | grep -o "bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted"
```

```output
bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
```

Evidence 2 — codex exec --help confirms --dangerously-bypass-approvals-and-sandbox is a real, first-class flag. Its description explicitly says it is intended for environments that are externally sandboxed — exactly this agent-vm setup. This is the only codex flag that skips bwrap entirely; every --sandbox mode (including danger-full-access) still invokes bwrap to enforce network isolation.

```bash
codex exec --help 2>&1 | grep -A1 "dangerously-bypass-approvals-and-sandbox" | head -3
```

```output
      --dangerously-bypass-approvals-and-sandbox
          Skip all confirmation prompts and execute commands without sandboxing. EXTREMELY
```

Evidence 3 — src/gateway/review_engine.py now passes --dangerously-bypass-approvals-and-sandbox in place of --full-auto + --sandbox danger-full-access. The new comment block explains why, so the next cleanup pass cannot silently put bwrap back.

```bash
git diff origin/main -- src/gateway/review_engine.py | grep -E "^[-+]" | grep -v "^[-+][-+][-+]"
```

```output
-                "--full-auto",
-                "--sandbox",
-                "danger-full-access",
+                # Host lacks CAP_NET_ADMIN, so any --sandbox mode (including
+                # danger-full-access) fails in bwrap's unshare-net with
+                # "loopback: Failed RTM_NEWADDR". The bypass flag skips bwrap
+                # entirely. Safe here: the host IS the external sandbox.
+                "--dangerously-bypass-approvals-and-sandbox",
```

Evidence 4 — With the new flag, codex is reachable from a subprocess. A trivial prompt round-trips through the model without any 'bwrap: loopback' line in stderr. We grep for the OK reply and explicitly assert the bwrap signature is absent.

```bash
out=$(timeout 30 codex exec --dangerously-bypass-approvals-and-sandbox --ephemeral --color never "reply with the single word OK and nothing else" 2>&1); echo "$out" | grep -q "^OK$" && echo "model replied: OK"; echo "$out" | grep -q "bwrap: loopback" && echo "BUG: bwrap still invoked" || echo "bwrap not invoked: confirmed"
```

```output
model replied: OK
bwrap not invoked: confirmed
```

Evidence 5 — A new pytest asserts the bypass flag is present and --sandbox / --full-auto / danger-full-access are all absent from the codex argv. This guards against a 'tidy up' revert — if anyone puts --sandbox back, this test fails.

```bash
uv run pytest tests/gateway/test_review_engine.py::TestHandleOrchestration::test_codex_argv_uses_bypass_flag_not_sandbox -q 2>&1 | grep -oE "[0-9]+ passed"
```

```output
1 passed
```

Evidence 6 — All 64 tests in the review_engine module pass with the new argv (63 existing + 1 new regression guard). Nothing else had to change.

```bash
uv run pytest tests/gateway/test_review_engine.py -q 2>&1 | grep -oE "[0-9]+ passed"
```

```output
64 passed
```
