# Work log — 2026-04-23 opencode-reviewer wave

Three merged PRs in one arc: re-framing the opencode reviewer prompt, unifying the reconcile-vs-close-wave teardown flow, and hotfixing a live breakage the first PR caused.

| PR | Task | Branch | Merged |
| --- | --- | --- | --- |
| #193 | T-268 — rewrite opencode prompt + drop `--pure` | `wt-opencode-prompt-rewrite` | 2026-04-23T09:00:20Z |
| #194 | T-270 — reconcile delegates to close-wave for clean worktrees | `wt-reconcile-close-wave-delegation` | 2026-04-23T10:53:20Z |
| #195 | T-272 HOTFIX — restore `--pure` (T-268 broke live PR reviews) | `wt-opencode-pure-hotfix` | 2026-04-23T10:53:30Z |

## T-268 / PR #193 — opencode prompt rewrite

**Scope.** Rewrite `.github/opencode/prompts/review.md` using codex's prompt as the scaffold. Drop "first-pass / cheap checks / leave architectural judgement for the cloud reviewer" framing; adopt "deep verification review" role, 7-step read-the-code checklist, evidence-outside-the-diff requirement. Also remove `--pure` from `OpencodeReviewer._build_args` under the hypothesis that it disabled tool access.

**Files changed.** `.github/opencode/prompts/review.md` (107→113 lines), `src/gateway/review_loop.py` (`_build_args` helper extracted), `tests/gateway/test_review_loop.py` (+4 pin tests), `docs/demos/wt-opencode-prompt-rewrite/`.

**Quality gate.** 750 → 754 tests passing, 1 xfailed, all green.

**Follow-up that fell out.** PR #193's own opencode review returned `:pass:` with no findings. The agent's shutdown learnings flagged this as insufficient evidence — N=1 on a small, clean diff cannot distinguish "rewrite worked" from "PR was clean enough to pass." T-272 below is the hotfix that eventually arose from this.

## T-270 / PR #194 — reconcile delegates to close-wave

**Scope.** Reconcile's Case A and Case C teardown destroys `shutdown-artifacts/{work-log,learnings}.md` before close-wave can archive them (observed during T-268's close-out — reconcile ran, `git worktree remove --force` vaporized the artifacts, T-269 close-off could not complete). Wire a completed-cleanly predicate into reconcile Step 5 so clean worktrees are handed off to close-wave for archive → pr-postprocessor → teardown, rather than teardown-only.

**Files changed.** `plugins/cloglog/skills/reconcile/SKILL.md` (new Step 5.0 Close-wave delegation), `plugins/cloglog/skills/close-wave/SKILL.md` (new Invocation modes section), `docs/design/agent-lifecycle.md` (new §5.5 Teardown ownership — unified flow), `tests/plugins/test_reconcile_skill_structure.py` (new — 7 pin tests including leak-after-fix backstops), `docs/demos/wt-reconcile-close-wave-delegation/`.

**Quality gate.** 754 → 759 passing across three commits. Coverage 88.22%.

**Review cycle.** Codex rounds 1–3: (1) predicate-2 filtered `get_board` by `worktree_id` which on `TaskCard` is the main agent's UUID, not the target worktree's. (2) predicate-3 required `pr_merged=True` on every assigned task, stricter than the real completion contract — accepts `done`, `review+pr_merged=True`, and `review+skip_pr=True`. (3) Round-3 leak: primary predicate body was fixed, but three summary paraphrases in other docs still carried the old stricter wording. Fixed with leak-after-fix backstop pin tests.

**Key decision.** Close-wave already accepted a worktree argument, so reconcile only needed an entry-point shim documenting "when invoked from reconcile, skip Step 1.5 confirmation and override `<wave-name>`". Less-invasive than refactoring close-wave for single-worktree mode.

## T-272 / PR #195 HOTFIX — restore `--pure`

**Triggering breakage.** PR #194 itself received zero opencode coverage — every opencode turn logged `[backend] opencode output unparseable (pr=194, N bytes, tail='Calling multiple tools to gather context for the deep review...')`. The user flagged this live.

**Investigation.** `opencode run --help` says `--pure  run without external plugins`. Empirical test 2026-04-23: with `--pure`, `opencode run ... 'Read the first line of AGENTS.md'` emits a `Read AGENTS.md` tool call and returns the real content — i.e., **tools stay available under `--pure`**. Without `--pure`, the default plugin set activates and traps small models in agentic narration loops that never emit the final JSON. `parse_reviewer_output` then fails on the tool-call text. Root cause of PR #194's silence: removing `--pure` in T-268 activated the plugins, not "gave the model file access" as T-268 assumed.

**Files changed.** `src/gateway/review_loop.py` restored `"--pure"` in the argv. `.github/opencode/prompts/review.md` rewritten again to drop the now-dishonest "no tool access" claim and the 7-step checklist the plan briefed based on the wrong hypothesis. `tests/gateway/test_review_loop.py` pin tests flipped — `test_opencode_argv_passes_pure` with a T-272-regression docstring. `docs/demos/wt-opencode-pure-hotfix/`.

**Review cycle.** Codex round 1 MEDIUM: demo hardcoded `opencode` / `ollama/gemma4-e4b-32k` instead of reading `settings.opencode_cmd` / `settings.opencode_model`. Round 2 × 2 HIGH: (a) demo's live `opencode run` call runs under `showboat verify` on every `make quality` — a transient ollama/model issue would fail quality for unrelated reasons. Verify-safe demos use filesystem booleans, in-process parse round-trips, pre-captured static text. (b) Prompt's "no tool access" claim is factually wrong — `--pure` still exposes built-in tools.

**User decision.** Merged as-is (argv restored, prompt rewrite shipped even though the "no tool access" line is wrong). The deeper question — gemma4-e4b-32k rubber-stamps `:pass:` independent of prompt framing — deferred to T-274.

**Follow-up filed.** T-274 (id `5d5ae616-0b98-401e-90ca-3bf2ecdd48bd`): "Properly enable opencode agentic mode — investigate `--format json` event stream or alternative invocation preserving tool access AND final JSON." Normal priority; the hotfix is enough to unblock live PR reviews.

## Shutdown summary

| Worktree | PR | Shutdown path | Commits | Notes |
| --- | --- | --- | --- | --- |
| wt-opencode-prompt-rewrite | #193 | cooperative (auto, pre-T-270) | 1 | Artifacts lost to reconcile Case C teardown before T-270 landed — work-log content preserved only in this file's T-268 section. |
| wt-reconcile-close-wave-delegation | #194 | cooperative | 3 | Artifacts preserved to `/tmp/cloglog-reconcile-archive-20260423-135731/` before this close-wave. |
| wt-opencode-pure-hotfix | #195 | cooperative | 2 | Artifacts preserved to same archive. |

All three agents unregistered via tier-1 cooperative shutdown. No tier-2 `force_unregister` fallbacks.

## Integration verification

- `make quality` green on `origin/main` (af9a710) — no post-merge integration issues surfaced. All three PRs touched disjoint file sets aside from `.github/opencode/prompts/review.md` (T-268 then T-272 rewrote it in sequence — T-272 landed last and is the live state).
- No `mcp-server/src/**` changes in any of the three PRs — `make sync-mcp-dist` is a no-op.
- No DB migrations in any of the three PRs.

## State after this wave

- opencode reviewer back online — PR reviews post JSON reliably, prompt has the deep-verification framing (even though it also has one factually-wrong "no tool access" line tracked in T-274).
- Reconcile delegates to close-wave for cleanly-completed worktrees — artifact loss regression closed.
- Agent-lifecycle §5.5 is the authoritative spec for the unified teardown flow.
- T-269 / T-271 / T-273 close-off backlog tasks closed out by this PR (archived here instead of three separate close-off PRs).
- T-274 is the open follow-up for properly wiring opencode agentic mode with preserved JSON.

## Remote branches deleted as part of this close-wave

- `origin/wt-opencode-prompt-rewrite` (T-268, PR #193)
- `origin/wt-reconcile-close-wave-delegation` (T-270, PR #194)
- `origin/wt-opencode-pure-hotfix` (T-272, PR #195)

All three PRs merged; `deleteBranchOnMerge` is disabled at the repo level by design, so deletion happens here via the github-bot skill.
