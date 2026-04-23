# Stage A (opencode) is disabled by default via settings.opencode_enabled=False, and codex stops reviewing docs/demos/ proof-of-work artifacts.

*2026-04-23T11:54:12Z by Showboat 0.6.1*
<!-- showboat-id: 3e059c48-a508-42b9-85ff-757cf30a5690 -->

### Change 1 — `settings.opencode_enabled` flag (default OFF)

One global Settings boolean gates stage A. Default is `False` on purpose:
`gemma4-e4b-32k` rubber-stamps `:pass:` regardless of prompt framing, so
stage A under the default local model produces only noise. Flip the flag
once T-274 lands a reviewer model that defends severity — no code change
needed then.

```bash
grep -q "^    opencode_enabled: bool = False" src/shared/config.py && echo "opencode_enabled_default_false=yes" || echo "opencode_enabled_default_false=MISSING"
   grep -q "settings.opencode_enabled" src/gateway/review_engine.py && echo "stage_a_gate_reads_setting=yes" || echo "stage_a_gate_reads_setting=MISSING"
   grep -q "if self._opencode_available and settings.opencode_enabled:" src/gateway/review_engine.py && echo "stage_a_gate_shape=and_conjunction" || echo "stage_a_gate_shape=MISMATCH"
```

```output
opencode_enabled_default_false=yes
stage_a_gate_reads_setting=yes
stage_a_gate_shape=and_conjunction
```

### Change 2 — `docs/demos/` added to diff skip patterns

Proof-of-work under `docs/demos/<branch>/` is Showboat-rendered booleans
plus captured tool output, not reviewable code. One regex in the
`_DIFF_SKIP_PATTERNS` tuple makes every reviewer skip those sections.

```bash
grep -q "(\\^|/)docs/demos/" src/gateway/review_engine.py && echo "skip_pattern_registered=yes" || echo "skip_pattern_registered=MISSING"
```

```output
skip_pattern_registered=yes
```

### Proof 1 — `filter_diff` drops `docs/demos/` sections in process

Constructs a two-section diff (one `docs/demos/` + one `src/gateway/`),
calls the real `filter_diff`, and asserts the demo section is gone while
the code section survives. Pure function call — verify-safe.

```bash
uv run python docs/demos/wt-disable-opencode-skip-demos/proof_filter_diff.py
```

```output
filter_diff_dropped_demo_section=True
filter_diff_kept_src_section=True
filter_diff_proof=PASS
```

### Proof 2 — sequencer skips stage A when flag off, still runs stage B

Instantiates the real `ReviewEngineConsumer`, stubs `ReviewLoop` so each
stage is observable, and drives `_review_pr` under both
`opencode_enabled=False` and `True`. Asserts:

- flag **off** → stage A never runs, stage B (codex) runs once;
- flag **on**  → stage A runs once, stage B still runs once.

No DB, no network, no subprocess — verify-safe.

```bash
uv run python docs/demos/wt-disable-opencode-skip-demos/proof_sequencer.py
```

```output
stage_a_runs_when_disabled=0
stage_b_runs_when_disabled=1
stage_a_runs_when_enabled=1
stage_b_runs_when_enabled=1
sequencer_proof=PASS
```

### Round 2 — registration gate closes opencode-only + flag-off regression

Codex MEDIUM on PR #197 round 1: on an opencode-only host (codex binary
absent) with `opencode_enabled=False`, the consumer still registered but
neither stage ran, leaving PRs with no review and no skip comment.

Fix: `app.py` now computes `opencode_effective = opencode_ok AND
settings.opencode_enabled` and treats that as the registration input.
When codex is missing AND opencode is disabled, the consumer is NOT
registered; an ERROR log names the three inputs that produced the decision.

```bash
grep -q "opencode_effective = opencode_ok and settings.opencode_enabled" src/gateway/app.py && echo "effective_availability_computed=yes" || echo "effective_availability_computed=MISSING"
   grep -q "if codex_ok or opencode_effective:" src/gateway/app.py && echo "registration_gate_on_effective=yes" || echo "registration_gate_on_effective=MISSING"
   grep -q "Review pipeline disabled" src/gateway/app.py && echo "loud_error_on_no_runnable_stage=yes" || echo "loud_error_on_no_runnable_stage=MISSING"
```

```output
effective_availability_computed=yes
registration_gate_on_effective=yes
loud_error_on_no_runnable_stage=yes
```

### Pin tests still green

T-272's `test_opencode_argv_passes_pure` pin test must survive — T-275
deliberately keeps the `OpencodeReviewer` class and its `--pure` invariant
intact so T-274's agentic-mode investigation can still drive the loop.

```bash
grep -q "def test_opencode_argv_passes_pure" tests/gateway/test_review_loop.py && echo "t272_pin_test_present=yes" || echo "t272_pin_test_present=MISSING"
   grep -q "\"--pure\"" src/gateway/review_loop.py && echo "opencode_argv_still_has_pure=yes" || echo "opencode_argv_still_has_pure=MISSING"
```

```output
t272_pin_test_present=yes
opencode_argv_still_has_pure=yes
```
