# Learnings — 2026-04-23 opencode-reviewer wave

Consolidated from the three shutdown-artifacts/learnings.md files produced by T-268, T-270, and T-272 agents. Patterns worth future agents' attention; CLAUDE.md absorption decisions noted per item.

## 1. `opencode run --pure` means "no external plugins", NOT "no tool access"

**Source:** T-272 (PR #195). Empirically verified 2026-04-23.

`opencode run --help` literally says `--pure  run without external plugins`. Under `--pure`, built-in Read / Bash / Edit tools remain available — confirmed by running `opencode run --pure --model ollama/gemma4-e4b-32k --log-level ERROR --dangerously-skip-permissions -- 'Read the first line of AGENTS.md'` and getting back a real Read tool call plus the file content.

Without `--pure`, the default plugin set activates and traps small models in agentic narration loops ("Calling multiple tools to gather context..."). Output is then tool-call text, never a JSON blob, and `parse_reviewer_output` fails silently on every turn.

**Live production impact.** Removing `--pure` in T-268 took opencode reviews offline from PR #193 merge through PR #195 merge. Every PR in that window got zero opencode coverage.

**CLAUDE.md absorption:** YES. Added to the "Automated code review" section.

## 2. Small local models rubber-stamp `:pass:` regardless of prompt framing

**Source:** T-272 (PR #195) shutdown learnings. Cross-validated against PR #190 (pre-T-268 prompt: `:pass:` + `[CRITICAL]` self-contradiction), PR #193, #194, #195 (all gemma `:pass:`; codex found real HIGH findings on #194 and #195).

gemma4-e4b-32k (opencode stage A) does not have the reasoning depth to defend severity judgements. The T-268 "deep verification + 7-step checklist" prompt did not change this. The T-272 "reason about the diff" prompt will not change this either. Prompt engineering alone is a dead end for this class of regression.

When opencode's quality becomes a priority, the levers are: (a) scope opencode to narrow mechanical checks within its reasoning ceiling, (b) upgrade to a bigger local model (qwen2.5:32b+ / llama3.3:70b), or (c) use a cheap API model for stage A. Measure candidate models against known-bug PRs (#178 agent-token hole, #191 MCP bearer hole, #187 gateway-owns-no-tables) before choosing.

**CLAUDE.md absorption:** YES. Added as a reviewer-expectations note.

## 3. `showboat verify` reruns every `exec` block on `make quality`

**Source:** T-272 codex round 2 HIGH.

`scripts/check-demo.sh` is a `make quality` step that reruns every `uvx showboat exec` block and byte-compares the output to what was captured. Any `exec` that depends on a live service (ollama model availability, external API, transient network) will intermittently fail `make quality` for reasons unrelated to the code under review.

Verify-safe demos (canonical example: `docs/demos/wt-f47-two-stage-review/T-248/`) use filesystem booleans, in-process parse round-trips via `python3 -c "..."`, and pre-captured static text only. For "proof the CLI does X" evidence, run the live call **once, out of band**, and embed the result as a `showboat note` (static text).

**CLAUDE.md absorption:** YES. Existing "Demo scripts must not call `uv run pytest`" guidance extended with the broader "no live-service calls in `exec`" rule.

## 4. API-boundary fields ≠ SQLAlchemy-model fields for close-off tasks

**Source:** T-270 codex round 1.

`TaskCard` / `TaskResponse` expose `worktree_id`, which is deliberately the **main agent's** UUID on close-off task rows (so `get_my_tasks` surfaces the close-off card in the main session). The FK to the target worktree — `close_off_worktree_id` — lives on the SQLAlchemy `Task` model but **not** on `TaskCard` (see `src/board/schemas.py::TaskResponse`). A predicate filtering `get_board` by `worktree_id == <target_wt_id>` is structurally unsatisfiable for the target worktree.

Fix: match by `title == f"Close worktree {wt_name}"` — the deterministic template output at `src/board/templates.py:20`. That field IS on `TaskCard`.

**CLAUDE.md absorption:** YES. Added to the "Cross-Context Integration" section alongside the existing schema/model gotchas.

## 5. Leak-after-fix: grep every copy of a rule before shipping the fix

**Source:** T-270 codex round 3.

Reconcile's primary predicate-3 body was fixed in round 2, but three summary paraphrases elsewhere (reconcile's own Delegation summary, close-wave's Invocation-modes round-up, agent-lifecycle §5.5 item 1) still carried the stricter wrong form. A reader trusting any summary over the primary body would re-implement the wrong predicate.

Fix pattern: after fixing a primary rule, `grep -rn "<old wording>" docs/ plugins/ | wc -l` must return zero; ship a **backstop pin test** that asserts absence of every wrong phrasing in every file that carries the rule. Asserting absence of wrong wordings beats asserting presence of the right wording in one place — the former catches the leak-after-fix class automatically.

**CLAUDE.md absorption:** YES. Added as a short pattern to the "Path-composition conventions have three sides" guidance, generalizing from paths to any rule with multiple doc homes.

## 6. Hotfix scope discipline — isolate the minimum load-bearing change

**Source:** T-272 shutdown learnings.

T-272's plan bundled three changes (argv restore + prompt rewrite + live-exec demo). Only the argv restore was load-bearing on the PR #194 breakage; the other two introduced review findings that extended the PR cycle. When scoping a hotfix, isolate the minimum change that demonstrably fixes the breakage. Bundle "improvements" separately so they can stand or fall on their own merits and don't hold the hotfix hostage.

**CLAUDE.md absorption:** NO. Covered by the existing "Don't add features, refactor, or introduce abstractions beyond what the task requires" guidance at the system-prompt level.

## 7. Codex has a ~2-session-per-PR review budget

**Source:** T-270 PR #194 reviews.

Codex reviewed PR #194 twice (round 1 MEDIUM, round 2 MEDIUM + HIGH), then a round 3 on the post-round-2 commit, and then refused further review with "Review skipped: this PR already has the maximum of 2 bot review sessions. Request human review." The budget appears to reset across calendar windows, but future fixes shouldn't plan on repeated rounds. Before pushing a fix, sweep every occurrence of the pattern and bundle into one commit.

**CLAUDE.md absorption:** NO. Product/infrastructure behavior — likely to change — not a durable project invariant.

## 8. Heredocs inside `showboat exec` need quoted delimiters

**Source:** T-270 codex review.

`python3 - <<PY ... PY` inside a `uvx showboat exec ... bash '...'` lets bash expand backticks and `$()` inside the heredoc body before passing to python. Captured output then includes stray `status: command not found` errors from backtick-wrapped Markdown spans. `showboat verify` is byte-exact and passes, but the demo is polluted. Use `<<'PY'` (quoted delimiter) to pass every character literally.

**CLAUDE.md absorption:** NO. General bash idiom; surfaces rarely.

## 9. `mark_pr_merged` requires both `task_id` AND `worktree_id`

**Source:** T-272 shutdown learnings.

The MCP tool schema is `mark_pr_merged(task_id, worktree_id)`. The `pr_merged` inbox event payload does not carry `worktree_id` — use your registered worktree id from `register_agent`. Omitting it returns a Zod validation error, not a helpful "missing arg" message.

**CLAUDE.md absorption:** NO. Tool-specific surface; if it bites often, it should become an inbox-event enrichment (same shape T-NEW-a used for `pr_merged_notification`) rather than a CLAUDE.md rule.
